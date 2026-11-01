"""Runs a sequence step by step: conditions, triggers, pausing, stopping (ADR 0031).

The runner knows the tree, not the devices: an ``Executor`` carries out each
action and takes each frame. Between steps come the **safe points**, where a
stop or a pause asked for takes effect and the conditions of every enclosing
container are checked; before each frame, the triggers too. After each step the
progress goes to a ``Checkpoint``, from which a run can be resumed after a
restart: *start* runs again, finished containers are skipped, plans go on from
their counts, and the actions of unfinished containers run again.

*End* always runs, once *targets* is done, stopped with ``run_end`` or failed.
Cancelling the task that runs the sequence stops it at once, without *end*.
"""

from __future__ import annotations

import functools
import logging
import statistics
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import anyio
from pydantic import AwareDatetime, Field, ValidationError

from nocs.equipment.profiles import write_atomic
from nocs.sequence import sky
from nocs.sequence.model import (
    Action,
    Autofocus,
    Condition,
    Container,
    ExposurePlan,
    FailureKind,
    FocusMemory,
    PathKey,
    PlanRow,
    SelectFilter,
    Sequence,
    SequenceModel,
    Target,
    Trigger,
    UntilDawn,
    UntilTime,
    Wait,
    WhileAbove,
    key,
    plans,
)
from nocs.state import Json

log = logging.getLogger(__name__)

CLOUD_STARS = 3
"""A light frame with fewer stars than this (or a quarter of its row's recent ones) is
taken under clouds."""
GOOD_FRAMES = 5
WAIT_POLL = 30.0
"""Seconds between looks at the sky (or the clock) while a ``Wait`` waits."""
WAIT_STEP = 5.0
"""Seconds between safe points while a policy waits."""


@dataclass(frozen=True, slots=True)
class FrameResult:
    stars: int | None = None
    hfr: float | None = None
    frame: int | None = None
    """The saved frame's catalog id."""


class StepError(Exception):
    """A step failed with a kind of failure the recovery policies know (ADR 0032);
    ``role`` names the device behind a ``device`` failure, when it is known."""

    def __init__(self, kind: FailureKind, message: str, *, role: str | None = None) -> None:
        super().__init__(message)
        self.kind: FailureKind = kind
        self.role = role


class Executor(Protocol):
    """Carries out the sequence's steps on the rig."""

    async def action(self, action: Action, target: Target | None) -> dict[str, Json] | None:
        """Carry out one action; what came of it goes to the session's events."""
        ...

    async def frame(self, plan: ExposurePlan, row: PlanRow, target: Target | None) -> FrameResult:
        """Take and keep one frame of ``row``; the wheel already holds its filter."""
        ...

    async def paused(self) -> None:
        """The run has stopped at a safe point until resumed: lend the devices back."""
        ...

    async def resumed(self) -> None:
        """The run goes on after a pause, or stops: take the devices back."""
        ...

    def focuser_temperature(self) -> float | None: ...

    async def recover(self, error: StepError, attempt: int) -> str | None:
        """Before retrying a ``device`` failure for the ``attempt``-th time, try to bring
        the device back (ADR 0030); what was done, or ``None``. Raising is reported
        and the retry goes on."""
        ...


# -- checkpoint ---------------------------------------------------------------------


class PlanProgress(SequenceModel):
    done: list[int]
    """Frames taken per row."""
    row: int | None = None
    """The row of the batch in progress."""
    in_batch: int = 0


class Checkpoint(SequenceModel):
    """Where a run is, written after every step."""

    version: int = 1
    run: str
    sequence: str = ""
    """The sequence's id, to find its definition after a restart."""
    digest: str
    """The sequence's: a checkpoint is never resumed on another definition."""
    started: AwareDatetime
    restarts: int = 0
    finished: list[PathKey] = Field(default_factory=list[PathKey])
    """Containers done (in the current iteration of their parents)."""
    iterations: dict[PathKey, int] = Field(default_factory=dict[PathKey, int])
    plans: dict[PathKey, PlanProgress] = Field(default_factory=dict[PathKey, PlanProgress])
    focus: FocusMemory = Field(default_factory=FocusMemory)
    ending: bool = False
    """*End* has begun: a resumed run goes straight to it."""
    ended: AwareDatetime | None = None


class CheckpointFile:
    """The checkpoint of the run in progress, in one file replaced atomically."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Checkpoint | None:
        try:
            return Checkpoint.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as e:
            log.warning("ignoring an unreadable sequence checkpoint %s: %s", self._path, e)
            return None

    async def save(self, checkpoint: Checkpoint) -> None:
        data = checkpoint.model_dump_json(indent=1)
        await anyio.to_thread.run_sync(write_atomic, self._path, data)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)


# -- plans --------------------------------------------------------------------------


def next_row(plan: ExposurePlan, progress: PlanProgress) -> int | None:
    """The row of the next frame, or ``None`` when the plan is done."""
    left = [i for i, row in enumerate(plan.rows) if progress.done[i] < row.count]
    if not left:
        return None
    if plan.order == "in_turn":
        return left[0]
    current = progress.row
    if current in left and progress.in_batch < plan.batch:
        return current
    first = 0 if current is None else current + 1
    return min(left, key=lambda i: (i - first) % len(plan.rows))


def count_frame(plan: ExposurePlan, progress: PlanProgress, row: int) -> None:
    if progress.row != row or progress.in_batch >= plan.batch:
        progress.row = row
        progress.in_batch = 0
    progress.done[row] += 1
    progress.in_batch += 1


# -- events and status --------------------------------------------------------------


class RunState(StrEnum):
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    STOPPING = "stopping"
    ENDING = "ending"
    FINISHED = "finished"


class Outcome(StrEnum):
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"


class EventKind(StrEnum):
    STARTED = "started"
    RESUMED_AFTER_RESTART = "resumed_after_restart"
    ACTION = "action"
    FRAME = "frame"
    TRIGGER = "trigger"
    CONDITION = "condition"
    PAUSED = "paused"
    RESUMED = "resumed"
    FAILED = "failed"
    RECOVERY = "recovery"
    SKIPPED = "skipped"
    ENDING = "ending"
    ENDED = "ended"


@dataclass(frozen=True, slots=True)
class Event:
    time: datetime
    kind: EventKind
    message: str
    path: PathKey | None = None
    data: dict[str, Json] = field(default_factory=dict[str, Json])


@dataclass(frozen=True, slots=True)
class _Done[T]:
    value: T


class _Stop(Exception):
    def __init__(self, run_end: bool) -> None:
        self.run_end = run_end


class _Skip(Exception):
    """A policy gave the step up."""


class _SkipTarget(Exception):
    """A policy gave the step's target up."""


class _ConditionEnded(Exception):
    def __init__(self, container: PathKey, condition: Condition) -> None:
        self.container = container
        self.condition = condition


@dataclass(slots=True)
class _Scope:
    path: PathKey
    container: Container
    target: Target | None


# -- runner -------------------------------------------------------------------------


class Runner:
    def __init__(
        self,
        sequence: Sequence,
        executor: Executor,
        *,
        now: Callable[[], datetime],
        checkpoint: Checkpoint | None = None,
        save: Callable[[Checkpoint], Awaitable[None]] | None = None,
        on_event: Callable[[Event], None] | None = None,
        on_change: Callable[[], None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
        place: Callable[[], sky.Place | None] = lambda: None,
    ) -> None:
        """Run ``sequence`` afresh, or from ``checkpoint`` after a restart."""
        self._sequence = sequence
        self._sleep = sleep
        self._place = place
        self._reported: BaseException | None = None
        """The failure that ended the session, already in the events."""
        self._stars: dict[tuple[PathKey, int], list[int]] = {}
        """Star counts of a plan row's recent good frames, to tell clouds."""
        self._executor = executor
        self._now = now
        self._save_to = save
        self._on_event: Callable[[Event], None] = on_event or _ignore
        self._on_change = on_change or (lambda: None)
        self._resumed = checkpoint is not None
        if checkpoint is None:
            run = uuid.uuid4().hex[:12]
            checkpoint = Checkpoint(run=run, digest=sequence.digest(), started=now())
        else:
            if checkpoint.digest != sequence.digest():
                raise ValueError("the checkpoint belongs to another version of the sequence")
            if checkpoint.ended is not None:
                raise ValueError("that run has ended")
            checkpoint = checkpoint.model_copy(deep=True)
            checkpoint.restarts += 1
            # *start* gets the rig ready (cooling, unparking, guiding): again after a restart.
            checkpoint.finished = [
                p for p in checkpoint.finished if p != "start" and not p.startswith("start.")
            ]
        self._checkpoint = checkpoint
        self._state = RunState.RUNNING
        self._outcome: Outcome | None = None
        self._error: str | None = None
        self._scopes: list[_Scope] = []
        self._current: PathKey | None = None
        self._step: anyio.CancelScope | None = None
        self._pause_asked = False
        self._stop_asked: bool | None = None
        """``run_end`` of a stop asked for, until it takes effect."""
        self._resume = anyio.Event()
        self._filter: str | None = None
        """The filter the runner last selected; ``None`` when it does not know."""

    # -- control --------------------------------------------------------------------

    @property
    def state(self) -> RunState:
        return self._state

    @property
    def checkpoint(self) -> Checkpoint:
        return self._checkpoint

    def pause(self, *, now: bool = False) -> None:
        """Pause at the next safe point; ``now`` drops the step in progress (a frame)."""
        if self._state is not RunState.RUNNING:
            return
        self._pause_asked = True
        self._resume = anyio.Event()
        self._set_state(RunState.PAUSING)
        if now and self._step is not None:
            self._step.cancel()

    def resume(self) -> None:
        if self._state is RunState.PAUSING:
            self._pause_asked = False
            self._resume.set()  # the pause may be under way already
            self._set_state(RunState.RUNNING)
        elif self._state is RunState.PAUSED:
            self._resume.set()

    def stop(self, *, run_end: bool = True, now: bool = False) -> None:
        """Stop at the next safe point, then run *end* unless ``run_end`` is false."""
        if self._state not in (RunState.RUNNING, RunState.PAUSING, RunState.PAUSED):
            return
        self._stop_asked = run_end
        self._set_state(RunState.STOPPING)
        self._resume.set()
        if now and self._step is not None:
            self._step.cancel()

    # -- running --------------------------------------------------------------------

    async def run(self) -> Outcome:
        checkpoint = self._checkpoint
        if self._resumed:
            self._event(EventKind.RESUMED_AFTER_RESTART, f"restart {checkpoint.restarts}")
        else:
            self._event(EventKind.STARTED, self._sequence.name)
        outcome, run_end = Outcome.COMPLETED, True
        try:
            if not checkpoint.ending:
                await self._container(self._sequence.start, ("start",), None)
                await self._container(self._sequence.targets, ("targets",), None)
        except _Stop as stop:
            outcome, run_end = Outcome.STOPPED, stop.run_end
        except Exception as e:
            log.info("sequence %s failed: %s", self._sequence.name, e)
            outcome, self._error = Outcome.FAILED, str(e) or type(e).__name__
            if e is not self._reported:
                self._event(EventKind.FAILED, self._error, self._current)
        self._scopes.clear()
        self._stop_asked, self._pause_asked = None, False
        if run_end:
            await self._end()
        self._outcome = outcome
        checkpoint.ended = self._now()
        await self._save()
        self._set_state(RunState.FINISHED)
        self._event(EventKind.ENDED, outcome.value, data={"error": self._error})
        return outcome

    async def _end(self) -> None:
        self._set_state(RunState.ENDING)
        self._checkpoint.ending = True
        await self._save()
        self._event(EventKind.ENDING, "end of session")
        # Every step of *end* is tried, whatever happened to the one before. Pauses
        # and stops are not taken now.
        end = self._sequence.end
        for i, child in enumerate(end.children):
            path = ("end", str(i))
            try:
                if isinstance(child, Container):
                    await self._container(child, path, end.target)
                elif isinstance(child, ExposurePlan):
                    await self._plan(child, path, end.target)
                elif isinstance(child, Wait):
                    await self._wait_for(child, path, end.target)
                else:
                    await self._action(child, path, end.target)
            except Exception as e:
                log.info("end of session step %s failed: %s", key(path), e)
                self._event(EventKind.FAILED, str(e) or type(e).__name__, key(path))
        self._current = None

    async def _container(
        self, container: Container, path: tuple[str, ...], target: Target | None
    ) -> None:
        here = key(path)
        checkpoint = self._checkpoint
        if here in checkpoint.finished:
            return
        scope = _Scope(here, container, container.target or target)
        self._scopes.append(scope)
        try:
            iteration = checkpoint.iterations.get(here, 0)
            while container.repeat is None or iteration < container.repeat:
                for i, child in enumerate(container.children):
                    child_path = (*path, str(i))
                    await self._safe_point()
                    if isinstance(child, Container):
                        await self._container(child, child_path, scope.target)
                    elif isinstance(child, ExposurePlan):
                        await self._plan(child, child_path, scope.target)
                    elif isinstance(child, Wait):
                        await self._wait_for(child, child_path, scope.target)
                    else:
                        await self._action(child, child_path, scope.target)
                iteration += 1
                self._forget_inside(here)
                checkpoint.iterations[here] = iteration
                await self._save()
        except _ConditionEnded as ended:
            if ended.container != here:
                raise
            self._event(EventKind.CONDITION, f"{ended.condition.kind} ended it", here)
            self._forget_inside(here)
        except _SkipTarget:
            if container.target is None:
                raise
            self._event(EventKind.SKIPPED, f"target {container.target.name}", here)
            self._forget_inside(here)
        finally:
            self._scopes.pop()
        checkpoint.iterations.pop(here, None)
        checkpoint.finished.append(here)
        await self._save()

    def _forget_inside(self, container: PathKey) -> None:
        """Clear the progress of what lies inside ``container`` for its next iteration."""
        checkpoint = self._checkpoint
        prefix = container + "."
        checkpoint.finished = [p for p in checkpoint.finished if not p.startswith(prefix)]
        for mapping in (checkpoint.iterations, checkpoint.plans):
            for p in [p for p in mapping if p.startswith(prefix)]:
                del mapping[p]

    async def _action(self, action: Action, path: tuple[str, ...], target: Target | None) -> bool:
        """Carry out an action; ``False`` when a policy gave it up."""
        here = key(path)
        step = functools.partial(self._executor.action, action, target)
        try:
            while (done := await self._attempt(here, step)) is None:
                await self._safe_point()  # dropped by a pause or a stop: they take effect here
        except _Skip:
            self._event(EventKind.SKIPPED, action.kind, here)
            if isinstance(action, Autofocus):
                self._focused()  # the triggers try again at their next reason, not now
            await self._save()
            return False
        if isinstance(action, SelectFilter):
            self._filter = action.filter
        elif isinstance(action, Autofocus):
            self._focused()
        self._event(EventKind.ACTION, action.kind, here, done.value)
        await self._save()
        return True

    async def _plan(self, plan: ExposurePlan, path: tuple[str, ...], target: Target | None) -> None:
        here = key(path)
        progress = self._checkpoint.plans.setdefault(here, PlanProgress(done=[0] * len(plan.rows)))
        while (index := next_row(plan, progress)) is not None:
            row = plan.rows[index]
            await self._safe_point()
            # After each of these steps, back to the safe point: a pause there may
            # have let someone change the filter or move the focuser.
            if row.filter is not None and row.filter != self._filter:
                if not await self._action(SelectFilter(filter=row.filter), path, target):
                    return
                continue
            if await self._trigger(here, row, target):
                continue
            frame = functools.partial(self._frame, here, plan, index, target)
            try:
                done = await self._attempt(here, frame)
            except _Skip:
                self._event(EventKind.SKIPPED, "the rest of the plan", here)
                return
            if done is None:
                continue  # dropped by a pause or a stop
            result = done.value
            count_frame(plan, progress, index)
            focus = self._checkpoint.focus
            focus.frames += 1
            if result.hfr is not None:
                focus.add_hfr(row.filter, result.hfr)
            self._event(
                EventKind.FRAME,
                f"{row.filter or '-'} {row.exposure:g} s {progress.done[index]}/{row.count}",
                here,
                {"row": index, "stars": result.stars, "hfr": result.hfr, "id": result.frame},
            )
            await self._save()
            self._on_change()

    async def _frame(
        self, path: PathKey, plan: ExposurePlan, index: int, target: Target | None
    ) -> FrameResult:
        """Take one frame; a light frame with too few stars fails as clouds (ADR 0032)."""
        result = await self._executor.frame(plan, plan.rows[index], target)
        if plan.frame_type != "light" or result.stars is None:
            return result
        good = self._stars.setdefault((path, index), [])
        least = max(CLOUD_STARS, statistics.median(good) / 4) if good else CLOUD_STARS
        if result.stars < least:
            raise StepError("clouds", f"{result.stars} stars, fewer than {least:g}")
        good.append(result.stars)
        del good[:-GOOD_FRAMES]
        return result

    async def _attempt[T](self, path: PathKey, step: Callable[[], Awaitable[T]]) -> _Done[T] | None:
        """Run a step under the recovery policies (ADR 0032); ``None`` when a pause or a
        stop dropped it.

        Raises ``_Skip`` or ``_SkipTarget`` when the policy gives the step or its target
        up, and the failure itself when it ends the session. *End* tries each step once.
        """
        tries = 0
        while True:
            try:
                return await self._run_step(path, step)
            except Exception as e:
                if self._state is RunState.ENDING:
                    raise
                kind: FailureKind = e.kind if isinstance(e, StepError) else "other"
                policy = self._sequence.policy(kind)
                again = policy.retries is None or tries < policy.retries
                self._event(
                    EventKind.FAILED,
                    str(e) or type(e).__name__,
                    path,
                    {"kind": kind, "attempt": tries + 1, "then": "retry" if again else policy.then},
                )
                if again:
                    tries += 1
                    if isinstance(e, StepError) and e.kind == "device":
                        await self._recover(e, tries, path)
                    await self._wait(policy.wait)
                    continue
                match policy.then:
                    case "skip":
                        raise _Skip from e
                    case "skip_target":
                        raise _SkipTarget from e
                    case "pause":
                        self.pause()
                        await self._safe_point()
                        tries = 0
                    case "end":
                        self._reported = e
                        raise

    async def _recover(self, error: StepError, attempt: int, path: PathKey) -> None:
        try:
            done = await self._executor.recover(error, attempt)
        except Exception as e:
            self._event(EventKind.RECOVERY, f"recovery failed: {e}", path, {"role": error.role})
        else:
            if done is not None:
                self._event(EventKind.RECOVERY, done, path, {"role": error.role})

    async def _wait(self, seconds: float) -> None:
        """Wait, letting stops, pauses and conditions that end take effect meanwhile."""
        while seconds > 0:
            await self._safe_point()
            chunk = min(seconds, WAIT_STEP)
            await self._sleep(chunk)
            seconds -= chunk
        await self._safe_point()

    async def _trigger(self, path: PathKey, row: PlanRow, target: Target | None) -> bool:
        """Fire the first trigger that is due before this frame; whether one was."""
        for trigger in [t for scope in self._scopes for t in scope.container.triggers]:
            reason = self._due(trigger, row)
            if reason is not None:
                self._event(EventKind.TRIGGER, f"{trigger.kind}: {reason}", path)
                await self._action(Autofocus(), tuple(path.split(".")), target)
                return True
        return False

    def _due(self, trigger: Trigger, row: PlanRow) -> str | None:
        return trigger.due(
            self._checkpoint.focus,
            filter=row.filter if row.filter is not None else self._filter,
            temperature=self._executor.focuser_temperature(),
            now=self._now(),
            started=self._checkpoint.started,
        )

    def _focused(self) -> None:
        self._checkpoint.focus = FocusMemory(
            time=self._now(),
            filter=self._filter,
            temperature=self._executor.focuser_temperature(),
        )

    async def _run_step[T](
        self, path: PathKey, step: Callable[[], Awaitable[T]]
    ) -> _Done[T] | None:
        """Run one step, which a pause or a stop asked for ``now`` may drop (``None``)."""
        self._current = path
        self._on_change()
        with anyio.CancelScope() as scope:
            self._step = scope
            try:
                return _Done(await step())
            finally:
                self._step = None
        return None

    async def _safe_point(self) -> None:
        while True:
            if self._stop_asked is not None:
                raise _Stop(self._stop_asked)
            if not self._pause_asked:
                break
            await self._pause()
        now = self._now()
        for scope in self._scopes:
            for condition in scope.container.conditions:
                if not self._holds(condition, scope.target, now):
                    raise _ConditionEnded(scope.path, condition)

    def _holds(self, condition: Condition, target: Target | None, now: datetime) -> bool:
        match condition:
            case UntilTime():
                return condition.holds(now)
            case UntilDawn():
                return now < sky.dawn(self._where(), now, condition.darkness)
            case WhileAbove():
                return self._above(target, condition.altitude, now)

    def _above(self, target: Target | None, minimum: float, now: datetime) -> bool:
        if target is None or target.ra is None or target.dec is None:
            raise ValueError("an altitude needs a target with coordinates")
        altitude, horizon = sky.altitude(self._where(), target.ra, target.dec, now)
        return altitude >= max(minimum, horizon)

    def _where(self) -> sky.Place:
        place = self._place()
        if place is None:
            raise ValueError("the site is unknown: set it in the profile")
        return place

    async def _wait_for(self, wait: Wait, path: tuple[str, ...], target: Target | None) -> None:
        """Wait until the time, the dusk or the altitude, through safe points."""

        def ready() -> bool:
            now = self._now()
            if wait.time is not None:
                return now >= wait.time
            if wait.dusk is not None:
                return sky.dark(self._where(), now, wait.dusk)
            assert wait.altitude is not None
            return self._above(target, wait.altitude, now)

        here = key(path)
        self._current = here
        started = self._now()
        while not ready():
            self._on_change()
            await self._wait(WAIT_POLL)
        waited = (self._now() - started).total_seconds()
        self._event(EventKind.ACTION, "wait", here, {"waited": round(waited)})
        await self._save()

    async def _pause(self) -> None:
        self._pause_asked = False
        await self._save()
        await self._executor.paused()
        # Paused once the rig is lent back, unless resumed or stopped meanwhile.
        if not self._resume.is_set():
            self._set_state(RunState.PAUSED)
            self._event(EventKind.PAUSED, "paused", self._current)
            await self._resume.wait()
        await self._executor.resumed()
        if self._stop_asked is None:
            self._set_state(RunState.RUNNING)
            self._event(EventKind.RESUMED, "resumed", self._current)
        # Someone may have used the rig meanwhile.
        self._filter = None

    # -- reporting ------------------------------------------------------------------

    def status(self) -> dict[str, Json]:
        """The run as the state shows it."""
        checkpoint = self._checkpoint
        rows: dict[str, Json] = {}
        for path, plan, target in plans(self._sequence):
            progress = checkpoint.plans.get(path)
            done = progress.done if progress is not None else [0] * len(plan.rows)
            if path in checkpoint.finished or _inside_finished(path, checkpoint.finished):
                done = [row.count for row in plan.rows]
            rows[path] = {
                "target": target.name if target is not None else None,
                "rows": [
                    {
                        "filter": row.filter,
                        "exposure": row.exposure,
                        "count": row.count,
                        "done": done[i],
                    }
                    for i, row in enumerate(plan.rows)
                ],
            }
        return {
            "run": checkpoint.run,
            "name": self._sequence.name,
            "state": self._state.value,
            "started": checkpoint.started.isoformat(timespec="seconds"),
            "restarts": checkpoint.restarts,
            "current": self._current,
            "plans": rows,
            "outcome": self._outcome.value if self._outcome is not None else None,
            "error": self._error,
        }

    def _set_state(self, state: RunState) -> None:
        self._state = state
        self._on_change()

    def _event(
        self,
        kind: EventKind,
        message: str,
        path: PathKey | None = None,
        data: dict[str, Json] | None = None,
    ) -> None:
        self._on_event(Event(self._now(), kind, message, path, data or {}))

    async def _save(self) -> None:
        if self._save_to is not None:
            await self._save_to(self._checkpoint)


def _ignore(_: Event) -> None:
    pass


def _inside_finished(path: PathKey, finished: list[PathKey]) -> bool:
    return any(path.startswith(f + ".") for f in finished)
