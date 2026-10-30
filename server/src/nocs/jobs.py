"""Long-running operations (exposures, slews, autofocus…) and the resources they lock.

A job runs as a task, locks resources (equipment roles) while it runs, and
publishes its progress in the state tree under ``("jobs", <id>)``::

    {kind, resources, state, progress, message, error, result, started, finished}

Commands that would disturb a running job (changing the gain mid-exposure)
check the lock first and are refused with ``ResourceBusyError``.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum

from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("jobs",)
KEEP_FINISHED = 20


class JobState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceBusyError(Exception):
    def __init__(self, resource: str, kind: str, job_id: str) -> None:
        super().__init__(f"{resource} is busy ({kind} {job_id})")
        self.resource = resource
        self.job_id = job_id


class JobContext:
    """Handed to the job's function to report progress."""

    def __init__(self, manager: JobManager, job_id: str) -> None:
        self._manager = manager
        self.id = job_id

    def progress(self, fraction: float | None, message: str | None = None) -> None:
        """Report progress (0 to 1, or ``None`` when unknown) and what is happening."""
        if fraction is not None:
            fraction = min(max(fraction, 0.0), 1.0)
        self._manager._update(self.id, progress=fraction, message=message)  # pyright: ignore[reportPrivateUsage]


type JobFunction = Callable[[JobContext], Awaitable[Json]]


class JobManager:
    def __init__(self, store: StateStore, keep_finished: int = KEEP_FINISHED) -> None:
        self._store = store
        self._keep = keep_finished
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._locks: dict[str, str] = {}
        """Resource → id of the job holding it."""
        self._kinds: dict[str, str] = {}
        self._finished: list[str] = []
        store.set(ROOT, {})

    def holder(self, resource: str) -> str | None:
        """Id of the job that locks ``resource``, if any."""
        return self._locks.get(resource)

    def check_free(self, resources: Iterable[str]) -> None:
        for resource in resources:
            if (job_id := self._locks.get(resource)) is not None:
                raise ResourceBusyError(resource, self._kinds[job_id], job_id)

    def start(self, kind: str, resources: Iterable[str], run: JobFunction) -> str:
        """Lock ``resources`` and run ``run`` as a job; returns its id at once."""
        resources = sorted(set(resources))
        self.check_free(resources)
        job_id = uuid.uuid4().hex[:12]
        for resource in resources:
            self._locks[resource] = job_id
        self._kinds[job_id] = kind
        self._store.set(
            (*ROOT, job_id),
            {
                "kind": kind,
                "resources": list[Json](resources),
                "state": JobState.RUNNING.value,
                "progress": None,
                "message": None,
                "error": None,
                "result": None,
                "started": _now(),
                "finished": None,
            },
        )
        task = asyncio.create_task(self._run(job_id, run), name=f"job-{kind}")
        self._tasks[job_id] = task
        # A task cancelled before it starts never runs _run's handlers.
        task.add_done_callback(lambda _: self._finish(job_id, JobState.CANCELLED))
        return job_id

    def cancel(self, job_id: str) -> bool:
        """Ask a running job to stop; ``False`` if it is not running."""
        task = self._tasks.get(job_id)
        if task is None or task.done():
            if self._store.get((*ROOT, job_id)) is None:
                raise KeyError(job_id)
            return False
        task.cancel()
        return True

    async def wait(self, job_id: str) -> None:
        """Wait until a job has finished (for tests and composed workflows)."""
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.wait({task})

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks)

    async def _run(self, job_id: str, run: JobFunction) -> None:
        context = JobContext(self, job_id)
        try:
            result = await run(context)
        except asyncio.CancelledError:
            self._finish(job_id, JobState.CANCELLED)
        except Exception as e:
            log.info("job %s (%s) failed: %s", job_id, self._kinds[job_id], e)
            self._finish(job_id, JobState.FAILED, error=str(e) or type(e).__name__)
        else:
            self._finish(job_id, JobState.SUCCEEDED, result=result)

    def _update(self, job_id: str, **fields: Json) -> None:
        if job_id not in self._tasks:
            return
        with self._store.transaction():
            for key, value in fields.items():
                self._store.set((*ROOT, job_id, key), value)

    def _finish(
        self, job_id: str, state: JobState, *, error: str | None = None, result: Json = None
    ) -> None:
        if self._tasks.pop(job_id, None) is None:
            return  # already finished
        for resource in [r for r, holder in self._locks.items() if holder == job_id]:
            del self._locks[resource]
        with self._store.transaction():
            path = (*ROOT, job_id)
            self._store.set((*path, "state"), state.value)
            self._store.set((*path, "error"), error)
            self._store.set((*path, "result"), result)
            self._store.set((*path, "finished"), _now())
            if state is JobState.SUCCEEDED:
                self._store.set((*path, "progress"), 1.0)
                self._store.set((*path, "message"), None)
            self._finished.append(job_id)
            while len(self._finished) > self._keep:
                old = self._finished.pop(0)
                self._kinds.pop(old, None)
                self._store.delete((*ROOT, old))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")
