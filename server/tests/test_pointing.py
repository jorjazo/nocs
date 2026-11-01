"""Solve and sync against fakes: a camera that writes headers, a fake ASTAP, a mount."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fakeastap import calls, install_fake_astap, write_frame

from nocs.api.schemas import JobInfo, SolverState
from nocs.devices import Coordinates, FrameType
from nocs.equipment import Role
from nocs.imaging import KeptFrame, Shot, StarMetrics
from nocs.jobs import JobContext, JobManager
from nocs.mount.service import MountNotReadyError, PointingError
from nocs.pointing import PointingService, SolveOptions, offset
from nocs.solving import Astap, Failure, SolveError, SolverService, separation
from nocs.state import StateStore

# The fake ASTAP answers with the solution of a frame of M 8.
M8_RA, M8_DEC = 270.92750 / 15, -23.76287
MOUNT = Coordinates(18.07, -23.70)
TAKEN = datetime(2026, 10, 31, 3, 0, 0, tzinfo=UTC)

pytestmark = pytest.mark.filterwarnings("ignore:File may have been truncated")


class FakeCameraDevice:
    def __init__(self) -> None:
        self.binnings: list[int] = []
        self._binning = 1

    @property
    def binning(self) -> tuple[int, int]:
        return (self._binning, self._binning)

    @property
    def max_binning(self) -> int:
        return 4

    async def set_binning(self, x: int, y: int | None = None) -> None:
        await asyncio.sleep(0)
        self._binning = x
        self.binnings.append(x)


class FakeCapture:
    """Frames of the M 8 frame's size, taken while the job holds the camera."""

    def __init__(self, jobs: JobManager, directory: Path) -> None:
        self.jobs = jobs
        self.directory = directory
        self.device = FakeCameraDevice()
        self.shots: list[Shot] = []
        self.taken_with: list[tuple[float, int]] = []
        self.stars = StarMetrics(120, 3.2, 0.1)
        self.preview: KeptFrame | None = None
        """The frame behind the preview, as CaptureService keeps it."""

    def camera(self, role: Role) -> FakeCameraDevice:
        return self.device

    async def take(
        self,
        context: JobContext,
        role: Role,
        seconds: float,
        frame_type: FrameType | None = None,
        label: str = "",
    ) -> Shot:
        assert self.jobs.holder(role.value) == context.id
        assert frame_type is FrameType.LIGHT
        await asyncio.sleep(0)
        self.taken_with.append((seconds, self.device.binning[0]))
        path = write_frame(self.directory / f"shot{len(self.shots)}.fits")
        shot = Shot(path, path.stat().st_size, FrameType.LIGHT, TAKEN, seconds, None)
        self.shots.append(shot)
        return shot

    def kept(self, role: Role = Role.MAIN_CAMERA) -> KeptFrame | None:
        return self.preview

    async def measure(self, shot: Shot, *, discard: bool = True) -> StarMetrics:
        assert not discard  # the solver still needs the frame
        assert shot.path.exists()
        return self.stars


class FakeMounts:
    """A tracking mount that reports what it was last synced to."""

    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs
        self.where: Coordinates | None = MOUNT
        self.syncs: list[tuple[float, float, datetime | None, str | None]] = []
        self.refusal: Exception | None = None

    def position(self) -> Coordinates:
        if self.where is None:
            raise MountNotReadyError("the mount is not connected")
        return self.where

    async def sync(
        self,
        ra: float,
        dec: float,
        when: datetime | None = None,
        *,
        job: str | None = None,
        check: bool = True,
    ) -> Coordinates:
        if job is None:
            self.jobs.check_free([Role.MOUNT.value])
        else:
            assert self.jobs.holder(Role.MOUNT.value) == job
        if self.refusal is not None:
            raise self.refusal
        await asyncio.sleep(0)
        self.syncs.append((ra, dec, when, job))
        self.where = Coordinates(ra, dec)
        return self.where


class Rig:
    def __init__(self, directory: Path, astap: Astap | None) -> None:
        self.directory = directory
        self.store = StateStore()
        self.store.set(("cameras",), {"main_camera": {"exposure": 5.0, "field": {"height": 2.34}}})
        self.jobs = JobManager(self.store)
        self.capture = FakeCapture(self.jobs, directory)
        self.mount = FakeMounts(self.jobs)
        self.solver = SolverService(self.store, astap)
        self.service = PointingService(self.store, self.jobs, self.capture, self.solver, self.mount)

    async def solve(self, **options: Any) -> dict[str, Any]:
        job_id = self.service.start(SolveOptions(**options))
        await self.jobs.wait(job_id)
        job = self.store.get(("jobs", job_id))
        assert isinstance(job, dict)
        JobInfo.model_validate(job)
        return job

    def solver_state(self) -> dict[str, Any]:
        state = self.store.get(("solver",))
        assert isinstance(state, dict)
        SolverState.model_validate(state)
        return state


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(tmp_path, install_fake_astap(tmp_path, monkeypatch))


def test_offsets_are_on_the_sky() -> None:
    near_pole = offset(6.0, -80.0, 6.1, -80.0)
    assert near_pole.ra == pytest.approx(0.1 * 15 * 60 * 0.17365, rel=1e-4)
    assert near_pole.dec == 0
    assert near_pole.angle == pytest.approx(near_pole.ra, rel=1e-3)
    # Across 0 h, east (larger RA) is positive.
    across = offset(23.99, 10.0, 0.01, 10.5)
    assert across.ra == pytest.approx(0.02 * 15 * 60 * 0.98481, rel=1e-4)
    assert across.dec == pytest.approx(30)
    assert across.angle == pytest.approx(separation(23.99, 10.0, 0.01, 10.5) * 60)


async def test_solve_reports_the_offset_from_the_mount(rig: Rig) -> None:
    job = await rig.solve()
    assert job["state"] == "succeeded", job["error"]
    assert job["kind"] == "solve"
    # The mount must not move under the frame; an exposure's locks come along.
    assert job["resources"] == ["filter_wheel", "focuser", "main_camera", "mount"]
    # The camera's exposure, its binning, and a hint from the mount.
    assert rig.capture.taken_with == [(5.0, 1)]
    [command] = calls(rig.directory)
    assert command[command.index("-ra") + 1] == f"{MOUNT.ra:.6f}"
    assert command[command.index("-z") + 1] == "2"  # from the measured HFR

    last = rig.solver_state()["last"]
    assert job["result"] == last
    assert last["ra"] == pytest.approx(M8_RA, abs=1e-4)
    assert last["dec"] == pytest.approx(M8_DEC, abs=1e-4)
    assert last["mount"] == {"ra": MOUNT.ra, "dec": MOUNT.dec}
    expected = offset(MOUNT.ra, MOUNT.dec, last["ra"], last["dec"])
    assert last["offset"] == {"angle": expected.angle, "ra": expected.ra, "dec": expected.dec}
    assert last["offset"]["ra"] < 0 < last["offset"]["angle"]  # M 8 is west of the mount
    assert last["taken"] == (TAKEN - timedelta(seconds=2.5)).isoformat(timespec="seconds")
    assert last["synced"] is False
    assert rig.mount.syncs == []
    assert not rig.capture.shots[0].path.exists()


async def test_solve_and_sync(rig: Rig) -> None:
    job = await rig.solve(sync=True, exposure=3)
    assert job["state"] == "succeeded", job["error"]
    [(ra, dec, when, job_id)] = rig.mount.syncs
    assert (ra, dec) == pytest.approx((M8_RA, M8_DEC), abs=1e-4)
    assert when == TAKEN - timedelta(seconds=1.5)  # mid-exposure
    assert job_id is not None
    assert rig.solver_state()["last"]["synced"] is True
    assert job["result"]["synced"] is True

    with pytest.raises(PointingError, match="already synced"):
        await rig.service.sync()


async def test_sync_after_a_plain_solve(rig: Rig) -> None:
    with pytest.raises(PointingError, match="no frame has been solved"):
        await rig.service.sync()
    await rig.solve()
    described = await rig.service.sync()
    assert described["synced"] is True
    [(ra, _, when, job_id)] = rig.mount.syncs
    assert ra == pytest.approx(M8_RA, abs=1e-4)
    assert when == TAKEN - timedelta(seconds=2.5)
    assert job_id is None
    assert rig.solver_state()["last"]["synced"] is True


async def test_no_sync_once_the_mount_moved(rig: Rig) -> None:
    await rig.solve()
    rig.mount.where = Coordinates(MOUNT.ra, MOUNT.dec + 0.5)
    with pytest.raises(PointingError, match=r"moved 30\.0 arcminutes"):
        await rig.service.sync()
    assert rig.mount.syncs == []


def keep_preview(rig: Rig, pointing: Coordinates | None = MOUNT) -> Path:
    path = write_frame(rig.directory / "preview.fits")
    shot = Shot(path, path.stat().st_size, FrameType.LIGHT, TAKEN, 4.0, None)
    rig.capture.preview = KeptFrame(shot, owned=True, pointing=pointing, stars=80, hfr=1.6)
    return path


async def test_solve_the_frame_behind_the_preview(rig: Rig) -> None:
    with pytest.raises(PointingError, match="no frame to solve"):
        rig.service.start_kept()
    path = keep_preview(rig)
    job_id = rig.service.start_kept()
    await rig.jobs.wait(job_id)
    job = rig.store.get(("jobs", job_id))
    assert isinstance(job, dict)
    assert job["state"] == "succeeded", job["error"]
    # Nothing to lock: no exposure, nothing moves.
    assert job["resources"] == []
    assert rig.capture.taken_with == []
    [command] = calls(rig.directory)
    # A link to the preview's frame, which a newer frame may delete meanwhile.
    assert command[command.index("-f") + 1] == str(path.with_name("preview.solving.fits"))
    assert command[command.index("-ra") + 1] == f"{MOUNT.ra:.6f}"
    assert command[command.index("-z") + 1] == "1"  # from the preview's HFR
    assert path.exists()
    assert not path.with_name("preview.solving.fits").exists()

    last = rig.solver_state()["last"]
    assert last["mount"] == {"ra": MOUNT.ra, "dec": MOUNT.dec}
    assert last["taken"] == (TAKEN - timedelta(seconds=2)).isoformat(timespec="seconds")
    # A sync to it later, while the mount is where it was.
    assert (await rig.service.sync())["synced"] is True


async def test_the_frame_behind_the_preview_went_away(rig: Rig) -> None:
    keep_preview(rig).unlink()
    job_id = rig.service.start_kept()
    await rig.jobs.wait(job_id)
    job = rig.store.get(("jobs", job_id))
    assert isinstance(job, dict)
    assert job["state"] == "failed"
    assert "newer frame" in str(job["error"])


async def test_a_refused_sync_fails_the_job_but_keeps_the_solution(rig: Rig) -> None:
    rig.mount.refusal = PointingError("Telescope Simulator is not tracking")
    job = await rig.solve(sync=True)
    assert job["state"] == "failed"
    assert "not tracking" in job["error"]
    last = rig.solver_state()["last"]
    assert last["synced"] is False
    assert last["offset"] is not None


async def test_binning_for_one_frame(rig: Rig) -> None:
    job = await rig.solve(binning=2)
    assert job["state"] == "succeeded", job["error"]
    assert rig.capture.taken_with == [(5.0, 2)]
    assert rig.capture.device.binnings == [2, 1]
    with pytest.raises(ValueError, match=r"binning must be 1\.\.4"):
        rig.service.start(SolveOptions(binning=5))


async def test_failure_deletes_the_frame_and_says_why(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FAKE_ASTAP_EXIT", "2")
    job = await rig.solve(sync=True)
    assert job["state"] == "failed"
    assert job["error"] == "not enough stars detected"
    assert rig.solver_state()["failure"]["reason"] == Failure.NO_STARS.value
    assert not rig.capture.shots[0].path.exists()
    assert rig.mount.syncs == []


async def test_without_a_mount_the_whole_sky_is_searched(rig: Rig) -> None:
    rig.mount.where = None
    with pytest.raises(MountNotReadyError):
        rig.service.start(SolveOptions(sync=True))
    job = await rig.solve()
    assert job["state"] == "succeeded", job["error"]
    [command] = calls(rig.directory)
    assert "-ra" not in command
    assert command[-2:] == ["-r", "180"]
    last = rig.solver_state()["last"]
    assert last["mount"] is None
    assert last["offset"] is None
    with pytest.raises(PointingError, match="not connected when the frame was taken"):
        await rig.service.sync()


async def test_refused_before_exposing_when_it_cannot_solve(tmp_path: Path) -> None:
    rig = Rig(tmp_path, None)
    with pytest.raises(SolveError, match="not installed"):
        rig.service.start(SolveOptions())
    assert rig.capture.shots == []
    with pytest.raises(ValueError, match="exposure"):
        rig.service.start(SolveOptions(exposure=0))
