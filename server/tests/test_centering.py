"""Centring against fakes: a mount with a pointing error, a solver that sees the true sky."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest

from nocs.api.schemas import CenteringState, JobInfo
from nocs.devices import Coordinates, FrameType
from nocs.equipment import Role
from nocs.imaging import Shot, StarMetrics
from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.mount.service import PointingError
from nocs.pointing import CenteringService, CenterOptions, PointingService
from nocs.solving import Failure, Hint, SolveError, SolveResult, separation
from nocs.solving.service import summary
from nocs.solving.solution import Solution, Wcs
from nocs.state import Json, StateStore

TARGET = Coordinates(0.5, -45.0)
ERROR = (15 / 60, 20 / 60)
"""The mount's pointing error: where it truly points minus where it says, degrees of
RA (along the axis, not on the sky) and Dec."""
TAKEN = datetime(2026, 10, 31, 3, 0, 0, tzinfo=UTC)


class FakeCameraDevice:
    binning = (1, 1)
    max_binning = 4

    async def set_binning(self, x: int, y: int | None = None) -> None:
        raise AssertionError("not rebinned")


class FakeCapture:
    def __init__(self, jobs: JobManager, directory: Path) -> None:
        self.jobs = jobs
        self.directory = directory
        self.taken = 0

    def camera(self, role: Role) -> FakeCameraDevice:
        return FakeCameraDevice()

    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot:
        assert self.jobs.holder(role.value) == context.id
        await asyncio.sleep(0)
        self.taken += 1
        path = self.directory / f"shot{self.taken}.fits"
        path.touch()
        return Shot(path, 0, FrameType.LIGHT, TAKEN, seconds, None)

    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics:
        return StarMetrics(80, 2.0, 0.1)


class FakeMount:
    """Says it points where it was sent, while it truly points ``error`` away; a sync
    moves what it says to the sync (without moving), unless it ignores syncs."""

    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs
        self.said = Coordinates(3.0, -60.0)
        self.error = ERROR
        self.ignores_syncs = False
        self.refusal: Exception | None = None
        self.slews: list[Coordinates] = []
        self.syncs: list[Coordinates] = []
        self.settled: list[float] = []
        self.hold: anyio.Event | None = None
        """While set, settling waits for it (to cancel a run in the middle)."""

    @property
    def sky(self) -> Coordinates:
        """Where it truly points."""
        return Coordinates((self.said.ra + self.error[0] / 15) % 24, self.said.dec + self.error[1])

    def position(self) -> Coordinates:
        return self.said

    async def sync(
        self,
        ra: float,
        dec: float,
        when: datetime | None = None,
        *,
        job: str | None = None,
        check: bool = True,
    ) -> Coordinates:
        assert job is not None
        assert self.jobs.holder(Role.MOUNT.value) == job
        await asyncio.sleep(0)
        self.syncs.append(Coordinates(ra, dec))
        if not self.ignores_syncs:
            sky = self.sky
            self.said = Coordinates(ra, dec)
            self.error = ((sky.ra - ra) * 15, sky.dec - dec)
        return self.said

    def check_goto(self, ra: float, dec: float, *, force: bool = False) -> None:
        if self.refusal is not None:
            raise self.refusal

    async def slew(
        self, context: JobContext, ra: float, dec: float, *, force: bool = False
    ) -> Coordinates:
        if self.jobs.holder(Role.MOUNT.value) != context.id:
            raise RuntimeError(f"job {context.id} does not hold the mount")
        await asyncio.sleep(0)
        self.slews.append(Coordinates(ra, dec))
        self.said = Coordinates(ra, dec)
        return self.said

    async def settle(self, seconds: float) -> None:
        self.settled.append(seconds)
        if self.hold is not None:
            await self.hold.wait()
        await asyncio.sleep(0)


class FakeSolver:
    """Solves every frame at the mount's true position, but for the failures queued."""

    def __init__(self, mount: FakeMount) -> None:
        self.mount = mount
        self.failures: list[SolveError] = []
        self.unavailable = False
        self.hints: list[Hint | None] = []

    def check(self, fov: float | None) -> object:
        if self.unavailable:
            raise SolveError("ASTAP is not installed", Failure.UNAVAILABLE)
        return None

    async def solve(
        self,
        image: Path,
        *,
        fov: float | None,
        hint: Hint | None,
        hfr: float | None = None,
        blind: bool = True,
    ) -> SolveResult:
        await asyncio.sleep(0)
        self.hints.append(hint)
        if self.failures:
            raise self.failures.pop(0)
        sky = self.mount.sky
        wcs = Wcs(500, 500, sky.ra * 15, sky.dec, -1e-3, 0, 0, 1e-3)
        solution = Solution(sky.ra, sky.dec, 3.6, 0.0, False, 1000, 1000, wcs)
        return SolveResult(solution, hinted=True, downsample=1, seconds=0.1)

    def annotate(self, result: SolveResult, fields: dict[str, Json]) -> dict[str, Json]:
        return summary(result) | fields


class Rig:
    def __init__(self, directory: Path) -> None:
        self.store = StateStore()
        self.store.set(("cameras",), {"main_camera": {"exposure": 5.0, "field": {"height": 1.0}}})
        self.jobs = JobManager(self.store)
        self.capture = FakeCapture(self.jobs, directory)
        self.mount = FakeMount(self.jobs)
        self.solver = FakeSolver(self.mount)
        self.pointing = PointingService(
            self.store, self.jobs, self.capture, self.solver, self.mount
        )
        self.service = CenteringService(self.store, self.jobs, self.pointing, self.mount)

    async def center(self, **options: Any) -> dict[str, Any]:
        job_id = self.service.start(TARGET.ra, TARGET.dec, CenterOptions(**options))
        await self.jobs.wait(job_id)
        return self.job(job_id)

    def job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(("jobs", job_id))
        assert isinstance(job, dict)
        JobInfo.model_validate(job)
        return job

    def state(self) -> dict[str, Any]:
        state = self.store.get(("centering",))
        assert isinstance(state, dict)
        CenteringState.model_validate(state)
        return state


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def angles(state: dict[str, Any]) -> list[float | None]:
    return [a["error"]["angle"] if a["error"] else None for a in state["attempts"]]


async def test_sync_until_within_tolerance(rig: Rig) -> None:
    job = await rig.center(settle=3)
    assert job["state"] == "succeeded", job["error"]
    assert job["kind"] == "center"
    assert job["resources"] == ["filter_wheel", "focuser", "main_camera", "mount"]
    state = rig.state()
    assert job["result"] == state
    assert state["state"] == "succeeded"
    assert state["phase"] is None
    assert state["target"] == {"ra": TARGET.ra, "dec": TARGET.dec}
    assert (state["method"], state["tolerance"], state["max_attempts"]) == ("sync", 1.0, 5)

    # The first frame lands the whole error away; synced, the next go to is spot on.
    first, second = state["attempts"]
    on_sky = (ERROR[0] * 0.70711 * 60, ERROR[1] * 60)  # cos(-45°)
    assert (first["error"]["ra"], first["error"]["dec"]) == pytest.approx(on_sky, abs=0.05)
    assert first["synced"] is True
    assert second["error"]["angle"] < 0.01
    assert rig.mount.slews == [TARGET, TARGET]
    assert rig.mount.settled == [3, 3]
    assert len(rig.mount.syncs) == 2  # the last frame too
    assert first["aim"] == second["aim"] == {"ra": TARGET.ra, "dec": TARGET.dec}
    assert second["solution"]["dec"] == pytest.approx(TARGET.dec)


async def test_offset_aims_off_by_the_error_without_syncing(rig: Rig) -> None:
    job = await rig.center(method="offset")
    assert job["state"] == "succeeded", job["error"]
    assert rig.mount.syncs == []
    first, second = rig.mount.slews
    assert first == TARGET
    assert second.ra == pytest.approx(TARGET.ra - ERROR[0] / 15)
    assert second.dec == pytest.approx(TARGET.dec - ERROR[1])
    assert angles(rig.state()) == [pytest.approx(22.65, abs=0.01), pytest.approx(0, abs=0.01)]
    assert [a["synced"] for a in rig.state()["attempts"]] == [False, False]


async def test_gives_up_after_the_attempts(rig: Rig) -> None:
    rig.mount.ignores_syncs = True
    job = await rig.center(attempts=3)
    assert job["state"] == "failed"
    assert job["error"] == "still 22.7 arcminutes from the target after 3 attempts"
    state = rig.state()
    assert state["state"] == "failed"
    assert state["error"] == job["error"]
    assert len(state["attempts"]) == 3
    assert len(rig.mount.slews) == 3


async def test_a_frame_that_does_not_solve_is_taken_again_without_moving(rig: Rig) -> None:
    rig.solver.failures = [SolveError("not enough stars detected", Failure.NO_STARS)]
    job = await rig.center()
    assert job["state"] == "succeeded", job["error"]
    failed, *solved = rig.state()["attempts"]
    assert failed["failure"] == {"reason": "no_stars", "message": "not enough stars detected"}
    assert failed["solution"] is None
    assert failed["error"] is None
    assert len(solved) == 2
    assert rig.mount.slews == [TARGET, TARGET]  # not after the failure
    assert len(rig.mount.settled) == 2


async def test_frames_that_never_solve(rig: Rig) -> None:
    rig.solver.failures = [SolveError("no solution", Failure.NO_SOLUTION)] * 3
    job = await rig.center(attempts=3)
    assert job["state"] == "failed"
    assert job["error"] == "none of 3 frames solved"
    assert [a["failure"]["reason"] for a in rig.state()["attempts"]] == ["no_solution"] * 3


async def test_no_star_database_ends_the_run_at_once(rig: Rig) -> None:
    rig.solver.failures = [SolveError("no star database for a 1° field", Failure.NO_DATABASE)]
    job = await rig.center()
    assert job["state"] == "failed"
    assert job["error"] == "no star database for a 1° field"
    assert rig.state()["attempts"] == []
    assert rig.capture.taken == 1


async def test_cancelling_stops_the_run(rig: Rig) -> None:
    rig.mount.hold = anyio.Event()
    job_id = rig.service.start(TARGET.ra, TARGET.dec, CenterOptions())
    for _ in range(20):
        await asyncio.sleep(0)
    assert rig.state()["phase"] == "settling"
    assert "attempt 1 of 5: settling" in rig.job(job_id)["message"]
    assert rig.jobs.cancel(job_id)
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "cancelled"
    state = rig.state()
    assert (state["state"], state["phase"], state["error"]) == ("cancelled", None, None)
    assert state["finished"] is not None
    assert rig.capture.taken == 0
    assert rig.jobs.holder(Role.MOUNT.value) is None


async def test_refused_while_another_job_holds_the_mount(rig: Rig) -> None:
    token = rig.jobs.reserve("move", [Role.MOUNT.value])
    with pytest.raises(ResourceBusyError, match="mount is busy"):
        rig.service.start(TARGET.ra, TARGET.dec, CenterOptions())
    rig.jobs.release(token)
    assert rig.store.get(("centering",)) is None

    # Inside a job that does not hold the mount, the go to is refused.
    async def other(context: JobContext) -> Json:
        return await rig.service.center(context, TARGET.ra, TARGET.dec, CenterOptions())

    job_id = rig.jobs.start("other", [Role.MAIN_CAMERA.value], other)
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["error"] == f"job {job_id} does not hold the mount"
    assert rig.state()["state"] == "failed"


async def test_refused_before_starting(rig: Rig) -> None:
    rig.mount.refusal = PointingError("the target is 12.0° below the horizon")
    with pytest.raises(PointingError, match="below the horizon"):
        rig.service.start(TARGET.ra, TARGET.dec, CenterOptions())
    rig.mount.refusal = None
    with pytest.raises(ValueError, match="attempts"):
        rig.service.start(TARGET.ra, TARGET.dec, CenterOptions(attempts=0))
    with pytest.raises(ValueError, match="tolerance"):
        rig.service.start(TARGET.ra, TARGET.dec, CenterOptions(tolerance=0))
    rig.solver.unavailable = True
    with pytest.raises(SolveError, match="not installed"):
        rig.service.start(TARGET.ra, TARGET.dec, CenterOptions())
    assert rig.store.get(("centering",)) is None
    assert rig.mount.slews == []


async def test_another_job_centres_with_its_own_locks(rig: Rig) -> None:
    """The way re-centring after a meridian flip will: inside its own job."""
    rig.mount.error = (0.0, 3 / 60)

    async def flip(context: JobContext) -> Json:
        return await rig.service.center(
            context, TARGET.ra, TARGET.dec, CenterOptions(method="offset", tolerance=0.5)
        )

    job_id = rig.jobs.start("flip", PointingService.resources(), flip)
    await rig.jobs.wait(job_id)
    job = rig.job(job_id)
    assert job["state"] == "succeeded", job["error"]
    assert job["result"]["job"] == job_id
    assert angles(rig.state()) == [pytest.approx(3, abs=0.01), pytest.approx(0, abs=0.01)]
    sky = rig.mount.sky
    assert separation(sky.ra, sky.dec, TARGET.ra, TARGET.dec) * 60 < 0.01
