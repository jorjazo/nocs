"""Sequences for the API: their definitions, and the one that runs (ADR 0031).

State under ``("sequence",)``::

    run:    the run in progress or the last one (``Runner.status``), or None
    events: its most recent events, oldest first: {time, kind, message, path}

A run is a job of kind ``sequence`` that holds the main camera, the filter
wheel, the focuser and the mount until it ends. Pausing lends them back
(``JobManager.suspend``); resuming takes them again or is refused, naming what
holds them. The checkpoint goes to ``<data dir>/sequence/run.json`` after every
step and is removed when the run ends; resuming one after a restart is phase 5.12.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from nocs.clock import Clock
from nocs.equipment import Role
from nocs.jobs import JobContext, JobManager
from nocs.sequence.model import Sequence
from nocs.sequence.rig import Parts, RigExecutor, take_back
from nocs.sequence.runner import CheckpointFile, Event, Outcome, Runner
from nocs.sequence.store import SequenceError, SequenceStore
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("sequence",)
RESOURCES = (
    Role.MAIN_CAMERA.value,
    Role.FILTER_WHEEL.value,
    Role.FOCUSER.value,
    Role.MOUNT.value,
)
KEEP_EVENTS = 50


class SequenceBusyError(Exception):
    """A sequence runs, or none does, when the command needs the other."""


class SequenceFailedError(Exception):
    pass


class SequenceService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        definitions: SequenceStore,
        checkpoint: CheckpointFile,
        clock: Clock,
        parts: Callable[[], Parts],
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._definitions = definitions
        self._checkpoint = checkpoint
        self._clock = clock
        self._parts = parts
        self._runner: Runner | None = None
        self._job: str | None = None
        self._running: str | None = None
        """Id of the sequence the run belongs to."""
        self._events: list[Json] = []
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
        if self._job is not None:
            raise SequenceBusyError(f"sequence {self._running} is running")
        sequence = self._definitions.get(sequence_id)
        if sequence is None:
            raise KeyError(sequence_id)
        parts = self._parts()
        parts.capture.camera(Role.MAIN_CAMERA)  # refused now, not in the job, without one
        self._jobs.check_free(RESOURCES)

        async def run(context: JobContext) -> Json:
            return await self._run(context, sequence, parts)

        self._job = self._jobs.start("sequence", RESOURCES, run)
        self._running = sequence_id
        return self._job

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

    async def _run(self, context: JobContext, sequence: Sequence, parts: Parts) -> Json:
        self._events = []
        executor = RigExecutor(context, self._jobs, self._store, parts)
        runner = Runner(
            sequence,
            executor,
            now=self._clock.now,
            save=self._checkpoint.save,
            on_event=self._on_event,
            on_change=self._publish,
        )
        self._runner = runner
        try:
            outcome = await runner.run()
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
            }
        )
        del self._events[:-KEEP_EVENTS]
        self._store.set((*ROOT, "events"), self._events)

    def _publish(self) -> None:
        if self._runner is not None:
            self._store.set((*ROOT, "run"), self._runner.status())


__all__ = ["SequenceBusyError", "SequenceError", "SequenceFailedError", "SequenceService"]
