"""Autofocus: a V-curve sweep with the main camera and the focuser (ADR 0021).

``AutofocusService.run`` works inside any job that holds the main camera and the
focuser, so the sequencer can call it from its own; ``start`` runs it in a job
of its own for the API, which also locks the filter wheel. A run:

1. measures a frame where the focuser is (too few stars: give up at once);
2. sweeps ``points`` positions ``step`` apart around it, every position
   reached moving the same way (backlash), each frame's stars measured in the
   worker while the next one is taken;
3. adds points on a side where the curve has not turned yet, up to a budget;
4. fits the curve and moves to its best focus;
5. checks a last frame there against the first one.

A failed or cancelled run takes the focuser back to where it started.

State under ``("autofocus",)``: ``None`` until the first run, then that run as
it goes (the most recent one, finished or not)::

    {job, state, phase, started, finished, step, start_position, start_hfr,
     start_stars, temperature, ambient, filter, points, fit, position, hfr,
     stars, problem, detail, suggested_overshoot, suggested_step}

Options left out come from the imaging train's sweep in the profile and from the
physical focuser's backlash settings (``options``). Finished runs are recorded
in the catalog.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import anyio

from nocs.devices import DeviceError, FrameType
from nocs.equipment import Role
from nocs.equipment.profiles import FocusSweep
from nocs.focus.curve import Fit
from nocs.focus.focusers import FocuserConfig
from nocs.focus.service import FocuserNotReadyError
from nocs.focus.sweep import (
    DEFAULT_CRITERIA,
    Criteria,
    Direction,
    Point,
    Problem,
    approach,
    assess,
    extension,
    suggest_step,
    sweep_positions,
)
from nocs.imaging import Shot, StarMetrics
from nocs.jobs import JobContext, JobManager
from nocs.state import Json, Path, StateStore
from nocs.storage import FocusRun
from nocs.storage.environment import number

log = logging.getLogger(__name__)

ROOT: Path = ("autofocus",)
RESOURCES = (Role.MAIN_CAMERA.value, Role.FOCUSER.value, Role.FILTER_WHEEL.value)
"""What a run of its own locks: a filter change would move the focus under it."""
SETTLE_INTERVAL = 0.5
"""How long the position must hold still for a focuser to count as stopped."""
SETTLE_TIMEOUT = 20.0


class FocuserDevice(Protocol):
    """What autofocus needs of a focuser (``nocs.devices.Focuser``)."""

    @property
    def position(self) -> int: ...
    @property
    def max_position(self) -> int | None: ...
    @property
    def temperature(self) -> float | None: ...
    @property
    def moving(self) -> bool: ...
    @property
    def can_abort(self) -> bool: ...
    async def move_to(self, position: int) -> None: ...
    async def abort(self) -> None: ...


class Focusers(Protocol):
    """The focuser role (``FocuserService``)."""

    def focuser(self) -> FocuserDevice: ...
    def backlash(self) -> FocuserConfig: ...


class Frames(Protocol):
    """Frames from the main camera inside a job (``CaptureService``)."""

    def camera(self, role: Role) -> object: ...
    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot: ...
    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics: ...


type Recorder = Callable[[FocusRun], Awaitable[None]]


type _Move = Callable[[int], Awaitable[None]]
type _Report = Callable[[str], None]
type _Shot = Callable[[], Awaitable[Measure]]
"""A frame taken; calling it measures the frame."""


class AutofocusError(Exception):
    def __init__(self, problem: Problem, detail: str, *, overshoot: int | None = None) -> None:
        super().__init__(detail)
        self.problem = problem
        self.overshoot = overshoot
        """For backlash: an overshoot that would take it up."""


class RunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Phase(StrEnum):
    STARTING = "starting"
    SWEEPING = "sweeping"
    MOVING = "moving"
    CHECKING = "checking"
    RESTORING = "restoring"


@dataclass(frozen=True, slots=True)
class AutofocusOptions:
    step: int
    """Focuser steps between points; depends on the focuser and the optics."""
    points: int = 9
    exposure: float = 2.0
    frames: int = 1
    """Frames per point; their median HFR counts."""
    direction: Direction = Direction.OUTWARD
    """Which way every position is reached (backlash)."""
    overshoot: int | None = None
    """Steps past a target when moving against ``direction``; ``None``: one ``step``."""
    extension: int = 4
    """Points that may be added on each side when the curve has not turned."""
    criteria: Criteria = DEFAULT_CRITERIA
    worse: float = 0.10
    """How much larger than the first frame's the last frame's HFR may be."""

    def check(self) -> None:
        if self.step < 1:
            raise ValueError("the step must be at least 1")
        if self.points < self.criteria.min_points:
            raise ValueError(f"a sweep needs at least {self.criteria.min_points} points")
        if not 0 < self.exposure <= 600:
            raise ValueError("the exposure must be 0..600 s")
        if not 1 <= self.frames <= 10:
            raise ValueError("frames per point must be 1..10")


@dataclass(frozen=True, slots=True)
class Measure:
    """A position's frames, measured."""

    position: int
    hfr: float | None
    stars: int


@dataclass(slots=True)
class _Run:
    """What the state shows of a run, kept as it goes."""

    job: str
    options: AutofocusOptions
    start_position: int
    temperature: float | None
    ambient: float | None = None
    filter: str | None = None
    started: str = field(default_factory=lambda: _now())
    state: RunState = RunState.RUNNING
    phase: Phase = Phase.STARTING
    start: Measure | None = None
    points: list[Point] = field(default_factory=list[Point])
    fit: Fit | None = None
    final: Measure | None = None
    problem: Problem | None = None
    detail: str | None = None
    suggested_overshoot: int | None = None
    finished: str | None = None

    def summary(self) -> dict[str, Json]:
        fit = self.fit
        return {
            "job": self.job,
            "state": self.state.value,
            "phase": self.phase.value if self.state is RunState.RUNNING else None,
            "started": self.started,
            "finished": self.finished,
            "step": self.options.step,
            "start_position": self.start_position,
            "start_hfr": self.start.hfr if self.start else None,
            "start_stars": self.start.stars if self.start else None,
            "temperature": self.temperature,
            "ambient": self.ambient,
            "filter": self.filter,
            "points": [
                {"position": p.position, "hfr": p.hfr, "stars": p.stars} for p in self.points
            ],
            "fit": (
                {
                    "a": fit.curve.a,
                    "b": fit.curve.b,
                    "c": fit.curve.c,
                    "r_squared": fit.r_squared,
                }
                if fit
                else None
            ),
            "position": self.final.position if self.final else None,
            "hfr": self.final.hfr if self.final else None,
            "stars": self.final.stars if self.final else None,
            "problem": self.problem.value if self.problem else None,
            "detail": self.detail,
            "suggested_overshoot": self.suggested_overshoot,
            "suggested_step": (
                suggest_step(fit, (self.options.points - 1) // 2)
                if fit and self.state is RunState.SUCCEEDED
                else None
            ),
        }


class AutofocusService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        focuser: Focusers,
        capture: Frames,
        *,
        sweep: Callable[[], FocusSweep | None] = lambda: None,
        profile: Callable[[], str | None] = lambda: None,
        record: Recorder | None = None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._focuser = focuser
        self._capture = capture
        self._train_sweep = sweep
        self._profile = profile
        self._record = record
        self._run: _Run | None = None
        store.set(ROOT, None)

    def options(
        self,
        *,
        step: int | None = None,
        points: int | None = None,
        exposure: float | None = None,
        frames: int | None = None,
        direction: Direction | None = None,
        overshoot: int | None = None,
    ) -> AutofocusOptions:
        """Options for a run: those given, then the imaging train's sweep and the
        focuser's backlash, then the defaults."""
        sweep = self._train_sweep()
        backlash = self._focuser.backlash()
        step = step if step is not None else sweep.step if sweep is not None else None
        if step is None:
            raise ValueError("autofocus needs a step: give one, or save one in the imaging train")
        defaults = AutofocusOptions(step=step)
        if direction is None:
            direction = Direction.INWARD if backlash.direction == "inward" else Direction.OUTWARD
        options = AutofocusOptions(
            step=step,
            points=_first(points, sweep.points if sweep else None, defaults.points),
            exposure=_first(exposure, sweep.exposure if sweep else None, defaults.exposure),
            frames=_first(frames, sweep.frames if sweep else None, defaults.frames),
            direction=direction,
            overshoot=overshoot if overshoot is not None else backlash.overshoot,
        )
        options.check()
        return options

    def start(self, options: AutofocusOptions) -> str:
        """Run autofocus in a job of its own; returns the job id."""
        options.check()
        self._focuser.focuser()  # fail now, not in the job, without a focuser
        self._capture.camera(Role.MAIN_CAMERA)
        self._jobs.check_free(RESOURCES)

        async def job(context: JobContext) -> Json:
            return await self.run(context, options)

        return self._jobs.start("autofocus", RESOURCES, job)

    async def run(self, context: JobContext, options: AutofocusOptions) -> dict[str, Json]:
        """Focus inside ``context``'s job, which must hold the main camera and the focuser.

        Returns the run's summary; raises ``AutofocusError`` (after moving the
        focuser back) when a quality check fails.
        """
        options.check()
        if self._jobs.holder(Role.FOCUSER.value) != context.id:
            raise RuntimeError(f"job {context.id} does not hold the focuser")
        focuser = self._focuser.focuser()
        run = _Run(
            context.id,
            options,
            focuser.position,
            focuser.temperature,
            ambient=number(self._store, ("weather", "temperature")),
            filter=_text(self._store.get(("filter_wheel", "filter"))),
        )
        self._run = run
        self._publish()
        try:
            await self._focus(context, focuser, run)
        except BaseException as e:
            run.state = RunState.CANCELLED if _cancelled(e) else RunState.FAILED
            if isinstance(e, AutofocusError):
                run.problem, run.detail = e.problem, str(e)
                run.suggested_overshoot = e.overshoot
            elif not _cancelled(e):
                run.detail = str(e) or type(e).__name__
            await self._restore(context, focuser, run)
            raise
        else:
            run.state = RunState.SUCCEEDED
        finally:
            run.finished = _now()
            self._publish()
            with anyio.CancelScope(shield=True):
                await self._keep(run)
        return run.summary()

    # -- internals ----------------------------------------------------------

    async def _focus(self, context: JobContext, focuser: FocuserDevice, run: _Run) -> None:
        options = run.options
        criteria = options.criteria
        maximum = focuser.max_position
        overshoot = options.overshoot if options.overshoot is not None else options.step
        planned = options.points + 2  # and the first and last frames

        def report(message: str) -> None:
            context.progress(min(len(run.points) + 1, planned) / planned, message)
            self._publish()

        async def move(target: int) -> None:
            for position in approach(
                focuser.position, target, options.direction, overshoot, maximum
            ):
                await focuser.move_to(position)

        async def frames(label: str) -> Measure:
            """The current position's frames, measured one after the other."""
            measures = [await self._measure(context, options, label) for _ in range(options.frames)]
            return _combine(focuser.position, measures, criteria)

        report("checking for stars")
        run.start = start = await frames("first frame: ")
        if start.hfr is None or start.stars < criteria.min_stars:
            raise AutofocusError(
                Problem.NO_STARS,
                f"{start.stars} stars where the focuser is ({criteria.min_stars} needed)",
            )

        run.phase = Phase.SWEEPING
        queue = sweep_positions(
            run.start_position, options.step, options.points, options.direction, maximum
        )
        budget = {Direction.INWARD: options.extension, Direction.OUTWARD: options.extension}
        while True:
            await self._sweep(context, run, queue, move, report)
            taken = [p.position for p in run.points]
            open_sides = [
                side
                for side, left in budget.items()
                if left > 0 and extension(taken, side, options.step, 1, maximum)
            ]
            verdict = assess(run.points, criteria, can_extend=open_sides)
            if verdict.fit is not None:
                run.fit = verdict.fit
                break
            if verdict.extend is None:
                assert verdict.problem is not None
                raise AutofocusError(
                    verdict.problem,
                    verdict.detail or verdict.problem.value,
                    overshoot=verdict.overshoot,
                )
            side = verdict.extend
            added = extension(taken, side, options.step, 1, maximum)
            budget[side] -= len(added)
            planned += len(added)
            # Nearest first; reached in the approach direction like the rest.
            queue = added
            log.info("autofocus: the curve has not turned yet, adding %s", added)

        run.phase = Phase.MOVING
        best = round(run.fit.curve.c)
        report(f"moving to {best}")
        await move(best)

        run.phase = Phase.CHECKING
        report("checking the focus")
        run.final = final = await frames("last frame: ")
        limit = start.hfr * (1 + options.worse)
        if final.hfr is None or final.stars < criteria.min_stars or final.hfr > limit:
            got = "no stars" if final.hfr is None else f"HFR {final.hfr:.2f}"
            raise AutofocusError(
                Problem.WORSE, f"{got} at {best}, against {start.hfr:.2f} at the start"
            )
        context.progress(1.0, f"focused at {best}")

    async def _sweep(
        self,
        context: JobContext,
        run: _Run,
        positions: Sequence[int],
        move: _Move,
        report: _Report,
    ) -> None:
        """Take frames at ``positions``; each is measured while the next one is taken."""
        options = run.options

        async def finish(position: int, shots: list[_Shot]) -> None:
            measures: list[Measure] = []
            for shot in shots:
                try:
                    measures.append(await shot())
                except Exception as e:  # a bad frame is a point without stars, not the end
                    log.warning("autofocus: no measurement at %d: %s", position, e)
                    measures.append(Measure(position, None, 0))
            run.points.append(_point(_combine(position, measures, options.criteria)))
            run.points.sort(key=lambda p: p.position)
            report(f"measured {position}")

        try:
            async with anyio.create_task_group() as group:
                for position in positions:
                    report(f"moving to {position}")
                    await move(position)
                    label = f"{position}: "
                    shots = [
                        await self._take(context, options, label) for _ in range(options.frames)
                    ]
                    group.start_soon(finish, position, shots)
        except BaseExceptionGroup as e:
            # Only this task raises (finish keeps its errors): give callers the error itself.
            if len(e.exceptions) == 1:
                raise e.exceptions[0] from None
            raise

    async def _take(self, context: JobContext, options: AutofocusOptions, label: str) -> _Shot:
        """Expose now; the returned function measures the frame later."""
        shot = await self._capture.take(
            context, Role.MAIN_CAMERA, options.exposure, FrameType.LIGHT, label
        )

        async def measure() -> Measure:
            metrics = await self._capture.measure(shot)
            return Measure(0, metrics.hfr, metrics.stars)

        return measure

    async def _measure(self, context: JobContext, options: AutofocusOptions, label: str) -> Measure:
        return await (await self._take(context, options, label))()

    async def _restore(self, context: JobContext, focuser: FocuserDevice, run: _Run) -> None:
        """Back to where the run started; never raises.

        A run cancelled in the middle of a move leaves the motor going: the ZWO EAF
        keeps moving to its target and refuses a new one until it gets there
        ("Error: 5"). So the focuser is stopped and left to settle first, and a
        refused move is tried once more.
        """
        run.phase = Phase.RESTORING
        self._publish()
        options = run.options
        overshoot = options.overshoot if options.overshoot is not None else options.step
        with anyio.CancelScope(shield=True):
            try:
                if focuser.can_abort:
                    await focuser.abort()
                await _settle(focuser)
                context.progress(None, f"back to {run.start_position}")
                for position in approach(
                    focuser.position,
                    run.start_position,
                    options.direction,
                    overshoot,
                    focuser.max_position,
                ):
                    try:
                        await focuser.move_to(position)
                    except DeviceError as e:
                        log.warning("autofocus: moving back to %d refused, again: %s", position, e)
                        await _settle(focuser)
                        await focuser.move_to(position)
            except (DeviceError, ConnectionError, TimeoutError, FocuserNotReadyError) as e:
                log.error("autofocus: could not move the focuser back: %s", e)

    async def _keep(self, run: _Run) -> None:
        """Record a finished run in the catalog; never raises."""
        if self._record is None:
            return
        summary = run.summary()
        try:
            await self._record(
                FocusRun(
                    started=run.started,
                    finished=run.finished or run.started,
                    profile=self._profile(),
                    filter=run.filter,
                    state=run.state.value,
                    problem=run.problem.value if run.problem else None,
                    start_position=run.start_position,
                    position=run.final.position if run.final else None,
                    start_hfr=run.start.hfr if run.start else None,
                    hfr=run.final.hfr if run.final else None,
                    focuser_temperature=run.temperature,
                    ambient_temperature=run.ambient,
                    run=json.dumps(summary),
                )
            )
        except Exception:
            log.exception("autofocus: cannot record the run")

    def _publish(self) -> None:
        if self._run is not None:
            self._store.set(ROOT, self._run.summary())


async def _settle(focuser: FocuserDevice) -> None:
    """Wait until the focuser is not moving and its position holds still (or give up)."""
    with anyio.move_on_after(SETTLE_TIMEOUT):
        last = focuser.position
        while True:
            await anyio.sleep(SETTLE_INTERVAL)
            now = focuser.position
            if not focuser.moving and now == last:
                return
            last = now


def _combine(position: int, measures: Sequence[Measure], criteria: Criteria) -> Measure:
    """One measure from a position's frames: the median of those with enough stars."""
    good = [m for m in measures if m.hfr is not None and m.stars >= criteria.min_stars]
    stars = round(statistics.median(m.stars for m in measures))
    if not good:
        return Measure(position, None, stars)
    hfrs = [m.hfr for m in good if m.hfr is not None]
    return Measure(position, round(statistics.median(hfrs), 3), stars)


def _first[T](*values: T | None) -> T:
    for value in values:
        if value is not None:
            return value
    raise ValueError("no value")


def _text(value: Json) -> str | None:
    return value if isinstance(value, str) else None


def _point(measure: Measure) -> Point:
    return Point(measure.position, measure.hfr, measure.stars)


def _cancelled(error: BaseException) -> bool:
    return isinstance(error, anyio.get_cancelled_exc_class())


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
