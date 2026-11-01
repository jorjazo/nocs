"""Sequences for the API: their definitions, and the one that runs (ADR 0031, 0032).

State under ``("sequence",)``::

    run:    the run in progress or the last one (``Runner.status``), or None
    events: its most recent events, oldest first: {time, kind, message, path, data}

A run is a job of kind ``sequence`` that holds the main camera, the filter
wheel, the focuser and the mount until it ends. Pausing lends them back
(``JobManager.suspend``); resuming takes them again or is refused, naming what
holds them. The checkpoint goes to ``<data dir>/sequence/run.json`` after every
step and is removed when the run ends; the run and all its events go to the
catalog. When nocsd starts and finds a checkpoint, ``recover`` resumes the run.
"""

from __future__ import annotations

import functools
import json
import logging
import math
from collections.abc import Awaitable, Callable
from typing import Protocol

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

from nocs.clock import Clock
from nocs.equipment import Role
from nocs.jobs import JobContext, JobManager
from nocs.sequence.model import Sequence, needs_site
from nocs.sequence.rig import Parts, RigExecutor, take_back
from nocs.sequence.runner import Checkpoint, CheckpointFile, Event, Outcome, Runner
from nocs.sequence.sky import Place
from nocs.sequence.store import SequenceError, SequenceStore
from nocs.state import Json, Path, StateStore
from nocs.storage import Session, SessionEvent

log = logging.getLogger(__name__)

ROOT: Path = ("sequence",)
RESOURCES = (
    Role.MAIN_CAMERA.value,
    Role.FILTER_WHEEL.value,
    Role.FOCUSER.value,
    Role.MOUNT.value,
)
KEEP_EVENTS = 50
MAX_RESTARTS = 3
"""Restarts of nocsd in one run after which it only runs *end* (ADR 0032)."""
RECOVERY_WAIT = 600.0
"""Seconds a restarted nocsd waits for the rig and the time before it only runs *end*."""


class SequenceBusyError(Exception):
    """A sequence runs, or none does, when the command needs the other."""


class SequenceFailedError(Exception):
    pass


class Recorder(Protocol):
    """Where runs and their events are kept: the catalog. Every method blocks."""

    def start_session(self, session: Session) -> int | None: ...
    def end_session(self, session_id: int, ended: str, outcome: str, error: str | None) -> None: ...
    def add_session_events(self, session_id: int, events: list[SessionEvent]) -> None: ...


class SequenceService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        definitions: SequenceStore,
        checkpoint: CheckpointFile,
        clock: Clock,
        parts: Callable[[], Parts],
        *,
        recorder: Recorder | None = None,
        profile: Callable[[], str | None] = lambda: None,
        place: Callable[[], Place | None] = lambda: None,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._definitions = definitions
        self._checkpoint = checkpoint
        self._clock = clock
        self._parts = parts
        self._recorder = recorder
        self._profile = profile
        self._place = place
        self._runner: Runner | None = None
        self._job: str | None = None
        self._running: str | None = None
        """Id of the sequence the run belongs to."""
        self._events: list[Json] = []
        self._record: MemoryObjectSendStream[Event] | None = None
        store.set(ROOT, {"run": None, "events": []})

    # -- definitions ----------------------------------------------------------------

    def all(self) -> dict[str, Sequence]:
        return self._definitions.load_all()

    def get(self, sequence_id: str) -> Sequence | None:
        return self._definitions.get(sequence_id)

    def put(self, sequence_id: str, sequence: Sequence) -> None:
        self._check_not_running(sequence_id)
        self._definitions.put(sequence_id, sequence)

    def delete(self, sequence_id: str) -> bool:
        self._check_not_running(sequence_id)
        return self._definitions.delete(sequence_id)

    # -- running --------------------------------------------------------------------

    def start(self, sequence_id: str) -> str:
        """Run a sequence as a job; returns the job id."""
        sequence = self._definitions.get(sequence_id)
        if sequence is None:
            raise KeyError(sequence_id)
        if needs_site(sequence) and self._place() is None:
            raise ValueError("this sequence asks about the sky: set the site in the profile")
        self._parts().capture.camera(Role.MAIN_CAMERA)  # refused now, not in the job
        return self._start(sequence_id, sequence, None)

    def pause(self, *, now: bool = False) -> None:
        self._active().pause(now=now)

    def resume(self) -> None:
        """Take the rig back and go on; ``ResourceBusyError`` while something else holds it."""
        runner = self._active()
        assert self._job is not None
        take_back(self._jobs, self._job, self._parts().guiding)  # refused now if it cannot
        runner.resume()

    def stop(self, *, run_end: bool = True, now: bool = False) -> None:
        self._active().stop(run_end=run_end, now=now)

    async def recover(
        self,
        connect: Callable[[], None],
        ready: Callable[[], bool],
        *,
        wait: float = RECOVERY_WAIT,
        poll: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    ) -> str | None:
        """Resume a run that a restart of nocsd interrupted (ADR 0032); its job id.

        Connects the rig and waits up to ``wait`` seconds until ``ready`` (the roles
        and the time); after that, after ``MAX_RESTARTS``, or when the definition
        changed, only *end* runs.
        """
        checkpoint = self._checkpoint.load()
        if checkpoint is None or checkpoint.ended is not None:
            return None
        sequence = self._definitions.get(checkpoint.sequence) if checkpoint.sequence else None
        if sequence is None:
            message = "cannot resume run %s: sequence %r is gone"
            log.warning(message, checkpoint.run, checkpoint.sequence)
            self._checkpoint.clear()
            return None
        reason = None
        if checkpoint.restarts >= MAX_RESTARTS:
            reason = f"restarted {checkpoint.restarts} times"
        elif checkpoint.digest != sequence.digest():
            reason = "the sequence changed since"
        connect()
        waited = 0.0
        while not ready() and waited < wait:
            await sleep(poll)
            waited += poll
        if reason is None and not ready():
            reason = f"the rig or the time was not ready after {wait:g} s"
        if reason is not None:
            log.warning("run %s: only running the end of the session: %s", checkpoint.run, reason)
            checkpoint = checkpoint.model_copy(update={"ending": True, "digest": sequence.digest()})
        else:
            log.info("resuming run %s of sequence %s", checkpoint.run, checkpoint.sequence)
        return self._start(checkpoint.sequence, sequence, checkpoint)

    def _start(self, sequence_id: str, sequence: Sequence, checkpoint: Checkpoint | None) -> str:
        if self._job is not None:
            raise SequenceBusyError(f"sequence {self._running} is running")
        parts = self._parts()
        self._jobs.check_free(RESOURCES)

        async def run(context: JobContext) -> Json:
            return await self._run(context, sequence_id, sequence, parts, checkpoint)

        self._job = self._jobs.start("sequence", RESOURCES, run)
        self._running = sequence_id
        return self._job

    async def _run(
        self,
        context: JobContext,
        sequence_id: str,
        sequence: Sequence,
        parts: Parts,
        checkpoint: Checkpoint | None,
    ) -> Json:
        self._events = []
        executor = RigExecutor(context, self._jobs, self._store, parts)
        runner = Runner(
            sequence,
            executor,
            now=self._clock.now,
            checkpoint=checkpoint,
            save=self._checkpoint.save,
            on_event=self._on_event,
            on_change=self._publish,
            place=self._place,
        )
        runner.checkpoint.sequence = sequence_id
        self._runner = runner
        send, receive = anyio.create_memory_object_stream[Event](math.inf)
        self._record = send
        outcome = Outcome.FAILED
        try:
            async with anyio.create_task_group() as group:
                group.start_soon(self._write, receive, sequence_id, sequence, runner)
                try:
                    outcome = await runner.run()
                finally:
                    self._record = None
                    send.close()
            self._checkpoint.clear()
        finally:
            if parts.guiding is not None:
                parts.guiding.guide_under(None)
            self._publish()
            self._runner = None
            self._job = None
            self._running = None
        status = runner.status()
        if outcome is Outcome.FAILED:
            raise SequenceFailedError(str(status["error"]))
        return status

    async def _write(
        self,
        events: MemoryObjectReceiveStream[Event],
        sequence_id: str,
        sequence: Sequence,
        runner: Runner,
    ) -> None:
        """Keep the run and its events in the catalog; a catalog that fails costs only that."""
        recorder = self._recorder
        checkpoint = runner.checkpoint
        session = Session(
            run=checkpoint.run,
            sequence=sequence_id,
            name=sequence.name,
            profile=self._profile(),
            started=checkpoint.started.isoformat(timespec="seconds"),
            ended=None,
            outcome=None,
            error=None,
            restarts=checkpoint.restarts,
            definition=sequence.model_dump_json(),
        )
        session_id: int | None = None
        if recorder is not None:
            session_id = await _quietly(lambda: recorder.start_session(session))
        async with events:
            async for event in events:
                batch = [event, *_ready(events)]
                if recorder is not None and session_id is not None:
                    rows = [_row(e) for e in batch]
                    add = functools.partial(recorder.add_session_events, session_id, rows)
                    await _quietly(add)
        status = runner.status()
        outcome = status["outcome"]
        if recorder is not None and session_id is not None and isinstance(outcome, str):
            ended = self._clock.now().isoformat(timespec="seconds")
            error = status["error"] if isinstance(status["error"], str) else None
            await _quietly(lambda: recorder.end_session(session_id, ended, outcome, error))

    def _active(self) -> Runner:
        if self._runner is None:
            raise SequenceBusyError("no sequence is running")
        return self._runner

    def _check_not_running(self, sequence_id: str) -> None:
        if self._running == sequence_id:
            raise SequenceBusyError(f"sequence {sequence_id} is running: stop it first")

    # -- state ----------------------------------------------------------------------

    def _on_event(self, event: Event) -> None:
        self._events.append(
            {
                "time": event.time.isoformat(timespec="seconds"),
                "kind": event.kind.value,
                "message": event.message,
                "path": event.path,
                "data": event.data,
            }
        )
        del self._events[:-KEEP_EVENTS]
        self._store.set((*ROOT, "events"), self._events)
        if self._record is not None:
            self._record.send_nowait(event)

    def _publish(self) -> None:
        if self._runner is not None:
            self._store.set((*ROOT, "run"), self._runner.status())


def _ready(events: MemoryObjectReceiveStream[Event]) -> list[Event]:
    """The events already waiting, without waiting for more."""
    batch: list[Event] = []
    while True:
        try:
            batch.append(events.receive_nowait())
        except (anyio.WouldBlock, anyio.EndOfStream):
            return batch


def _row(event: Event) -> SessionEvent:
    return SessionEvent(
        time=event.time.isoformat(timespec="seconds"),
        kind=event.kind.value,
        message=event.message,
        path=event.path,
        data=json.dumps(event.data),
    )


async def _quietly[T](call: Callable[[], T]) -> T | None:
    try:
        return await anyio.to_thread.run_sync(call)
    except Exception:
        log.exception("cannot keep the sequence's session in the catalog")
        return None


__all__ = ["SequenceBusyError", "SequenceError", "SequenceFailedError", "SequenceService"]
