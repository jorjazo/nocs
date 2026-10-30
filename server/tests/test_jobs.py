"""Jobs: lifecycle, progress, resource locks."""

import asyncio

import pytest

from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.state import Json, StateStore


@pytest.fixture
def store() -> StateStore:
    return StateStore()


def job(store: StateStore, job_id: str) -> dict[str, Json]:
    value = store.get(("jobs", job_id))
    assert isinstance(value, dict)
    return value


async def test_success_reports_progress_and_result(store: StateStore) -> None:
    manager = JobManager(store)
    seen: list[Json] = []

    async def run(context: JobContext) -> Json:
        context.progress(0.5, "halfway")
        seen.append(job(store, context.id)["message"])
        return {"answer": 42}

    job_id = manager.start("demo", ["camera"], run)
    assert job(store, job_id)["state"] == "running"
    assert manager.holder("camera") == job_id
    await manager.wait(job_id)
    finished = job(store, job_id)
    assert seen == ["halfway"]
    assert (finished["state"], finished["progress"], finished["result"]) == (
        "succeeded",
        1.0,
        {"answer": 42},
    )
    assert finished["finished"] is not None
    assert manager.holder("camera") is None


async def test_failure_records_the_error(store: StateStore) -> None:
    manager = JobManager(store)

    async def run(context: JobContext) -> Json:
        raise RuntimeError("the cable fell off")

    job_id = manager.start("demo", ["mount"], run)
    await manager.wait(job_id)
    assert job(store, job_id)["state"] == "failed"
    assert job(store, job_id)["error"] == "the cable fell off"
    assert manager.holder("mount") is None


async def test_locks_conflicting_jobs_and_commands(store: StateStore) -> None:
    manager = JobManager(store)
    release = asyncio.Event()

    async def run(context: JobContext) -> Json:
        await release.wait()
        return None

    job_id = manager.start("expose", ["main_camera"], run)
    with pytest.raises(ResourceBusyError, match=f"main_camera is busy \\(expose {job_id}\\)"):
        manager.start("expose", ["main_camera", "mount"], run)
    with pytest.raises(ResourceBusyError):
        manager.check_free(["main_camera"])
    manager.check_free(["mount"])  # the failed start locked nothing
    other = manager.start("slew", ["mount"], run)
    release.set()
    await manager.wait(job_id)
    await manager.wait(other)
    manager.check_free(["main_camera", "mount"])


async def test_cancel(store: StateStore) -> None:
    manager = JobManager(store)
    cleaned_up = asyncio.Event()

    async def run(context: JobContext) -> Json:
        try:
            await asyncio.sleep(60)
        finally:
            cleaned_up.set()
        return None

    job_id = manager.start("expose", ["main_camera"], run)
    await asyncio.sleep(0)
    assert manager.cancel(job_id)
    await manager.wait(job_id)
    assert cleaned_up.is_set()
    assert job(store, job_id)["state"] == "cancelled"
    assert not manager.cancel(job_id)  # already finished
    with pytest.raises(KeyError):
        manager.cancel("nope")


async def test_keeps_only_recent_finished_jobs(store: StateStore) -> None:
    manager = JobManager(store, keep_finished=2)

    async def run(context: JobContext) -> Json:
        return None

    ids = [manager.start("demo", [], run) for _ in range(4)]
    for job_id in ids:
        await manager.wait(job_id)
    jobs = store.get(("jobs",))
    assert isinstance(jobs, dict)
    assert sorted(jobs) == sorted(ids[2:])


async def test_close_cancels_running_jobs(store: StateStore) -> None:
    manager = JobManager(store)

    async def run(context: JobContext) -> Json:
        await asyncio.sleep(60)
        return None

    job_id = manager.start("demo", ["x"], run)
    await manager.close()
    assert job(store, job_id)["state"] == "cancelled"
