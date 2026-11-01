"""The polar alignment job against a fake mount with a polar error and knobs.

The fake mount tracks at the sidereal rate about its own axis: at a time t it points
at its own hour angle LST(t) - RA (the JNow RA it was sent to) and Dec, turned by its
polar error as ``nocs.align.polar.turn`` turns an aligned mount. Its clock moves
only when the rig works: an exposure, a slew, settling.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from nocs.align.polar import angles, pole, turn, vector
from nocs.align.service import PolarAlignmentService, PolarOptions
from nocs.api.schemas import JobInfo, PolarAlignmentState
from nocs.devices import Coordinates, Location
from nocs.equipment import HorizonPoint, Role
from nocs.jobs import JobContext, JobManager, ResourceBusyError
from nocs.mount.coords import jnow_to_j2000, sidereal_time
from nocs.mount.service import Frame, PointingError
from nocs.pointing.solve import FrameSolve, SolveOptions
from nocs.solving import Failure, SolveError, SolveResult
from nocs.solving.solution import Solution, Wcs
from nocs.state import StateStore

SITE = Location(-30.0277, -70.6733, 700)
START = datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
EXPOSURE = 4.0


class FakeClock:
    def __init__(self) -> None:
        self.time = START

    def now(self) -> datetime:
        return self.time

    def advance(self, seconds: float) -> None:
        self.time += timedelta(seconds=seconds)


class FakeMount:
    def __init__(self, jobs: JobManager, clock: FakeClock) -> None:
        self.jobs = jobs
        self.clock = clock
        self.site_: Location | None = SITE
        self.error = (45.0, -30.0)
        """Arcminutes: altitude (up) and azimuth (east, on the sky) of the axis."""
        self.sent = Coordinates(self.ra_at(-0.5), -60.0)
        """JNow; the mount points 30 min east of the meridian at -60°."""
        self.tracking = False
        self.slews: list[Coordinates] = []

    def ra_at(self, hour_angle: float) -> float:
        return (sidereal_time(SITE.longitude, self.clock.now()) - hour_angle) % 24

    def site(self) -> Location | None:
        return self.site_

    def position_jnow(self) -> Coordinates:
        return self.sent

    def sky(self) -> Coordinates:
        """Where it truly points now (J2000)."""
        now = self.clock.now()
        hour_angle = sidereal_time(SITE.longitude, now) - self.sent.ra
        lat = SITE.latitude
        p = pole(lat)
        h, d = angles(
            turn(
                vector(hour_angle, self.sent.dec),
                p,
                lat,
                altitude=self.error[0],
                azimuth=self.error[1],
            )
        )
        return jnow_to_j2000((sidereal_time(SITE.longitude, now) - h) % 24, d, now)

    def turn_knobs(self, altitude: float, azimuth: float) -> None:
        self.error = (self.error[0] + altitude, self.error[1] + azimuth)

    async def slew(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        *,
        force: bool = False,
        frame: Frame = "j2000",
    ) -> Coordinates:
        assert frame == "jnow"
        assert self.jobs.holder(Role.MOUNT.value) == context.id
        await asyncio.sleep(0)
        self.clock.advance(20)
        self.sent = Coordinates(ra, dec)
        self.slews.append(self.sent)
        return self.sent

    async def settle(self, seconds: float) -> None:
        await asyncio.sleep(0)
        self.clock.advance(seconds)

    async def set_tracking(
        self, on: bool | None, mode: str | None = None, *, job: str | None = None
    ) -> None:
        assert job is not None
        assert self.jobs.holder(Role.MOUNT.value) == job
        if on is not None:
            self.tracking = on


class FakePointing:
    """Takes and solves a frame where the mount truly points, but for queued failures;
    runs ``before[n]`` before the n-th frame (counted from 0)."""

    def __init__(self, jobs: JobManager, mount: FakeMount, clock: FakeClock) -> None:
        self.jobs = jobs
        self.mount = mount
        self.clock = clock
        self.frames = 0
        self.failures: list[SolveError] = []
        self.before: dict[int, Any] = {}
        self.unavailable = False

    def check(self, options: SolveOptions, role: Role = Role.MAIN_CAMERA) -> None:
        if self.unavailable:
            raise SolveError("ASTAP is not installed", Failure.UNAVAILABLE)

    @staticmethod
    def resources(role: Role = Role.MAIN_CAMERA) -> list[str]:
        return [role.value, Role.MOUNT.value, Role.FILTER_WHEEL.value, Role.FOCUSER.value]

    async def solve_frame(
        self, context: JobContext, options: SolveOptions, role: Role = Role.MAIN_CAMERA
    ) -> FrameSolve:
        assert self.jobs.holder(role.value) == context.id
        assert not options.sync
        action = self.before.pop(self.frames, None)
        if action is not None:
            action()
        self.frames += 1
        await asyncio.sleep(0)
        self.clock.advance(EXPOSURE / 2)
        sky = self.mount.sky()
        taken = self.clock.now()
        self.clock.advance(EXPOSURE / 2 + 3)
        if self.failures:
            raise self.failures.pop(0)
        wcs = Wcs(500, 500, sky.ra * 15, sky.dec, -1e-3, 0, 0, 1e-3)
        solution = Solution(sky.ra, sky.dec, 3.6, 0.0, False, 1000, 1000, wcs)
        result = SolveResult(solution, hinted=True, downsample=1, seconds=0.1)
        return FrameSolve(result, taken, None, None, 80, 2.0)


class Rig:
    def __init__(self) -> None:
        self.store = StateStore()
        self.jobs = JobManager(self.store)
        self.clock = FakeClock()
        self.mount = FakeMount(self.jobs, self.clock)
        self.pointing = FakePointing(self.jobs, self.mount, self.clock)
        self.horizon: list[HorizonPoint] | None = None
        self.service = PolarAlignmentService(
            self.store,
            self.jobs,
            self.pointing,
            self.mount,
            self.clock,
            horizon=lambda: self.horizon,
        )

    def state(self) -> dict[str, Any]:
        state = self.store.get(("polar_alignment",))
        assert isinstance(state, dict)
        PolarAlignmentState.model_validate(state)
        return state

    def job(self, job_id: str) -> dict[str, Any]:
        job = self.store.get(("jobs", job_id))
        assert isinstance(job, dict)
        JobInfo.model_validate(job)
        return job

    async def until(self, updates: int) -> None:
        """Wait for that many updates of the knobs' phase."""
        for _ in range(10_000):
            state = self.store.get(("polar_alignment",))
            if isinstance(state, dict) and len(state["updates"]) >= updates:  # pyright: ignore[reportArgumentType]
                return
            await asyncio.sleep(0)
        raise AssertionError(f"fewer than {updates} updates")


@pytest.fixture
def rig() -> Rig:
    return Rig()


async def test_measures_the_error_and_follows_the_knobs(rig: Rig) -> None:
    start = rig.mount.sent
    # The user turns the knobs before the 5th and the 7th frames (2 updates each).
    rig.pointing.before = {
        4: lambda: rig.mount.turn_knobs(-30, 20),
        6: lambda: rig.mount.turn_knobs(-15, 10),
    }
    job_id = rig.service.start(PolarOptions())
    await rig.until(5)
    state = rig.state()
    assert state["phase"] == "adjusting"
    assert state["options"]["side"] == "east"  # it pointed east of the meridian
    assert rig.mount.tracking
    # Turned 30° east twice: the RA grew by 2 h each time, at the same Dec.
    assert [round((s.ra - start.ra) % 24, 6) for s in rig.mount.slews] == [2.0, 4.0]
    assert all(s.dec == start.dec for s in rig.mount.slews)
    assert state["rotation"] == pytest.approx([30.0, 30.0], abs=0.01)
    assert state["warning"] is None
    updates = state["updates"]
    first = updates[0]["axis"]
    assert (first["altitude"], first["azimuth"]) == pytest.approx((45, -30), abs=0.05)
    # The fake turns its knobs from the pole each time: 1% apart (second order).
    assert updates[1]["knobs"] == pytest.approx({"altitude": -30, "azimuth": 20}, abs=0.3)
    last = state["axis"]
    assert (last["altitude"], last["azimuth"]) == pytest.approx((0, 0), abs=0.05)
    assert state["aligned"]

    rig.service.finish()
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "succeeded"
    state = rig.state()
    assert state["state"] == "succeeded"
    assert state["phase"] is None
    assert rig.mount.slews[-1] == start  # back to the start


async def test_turns_west_of_the_meridian_and_stays_when_asked(rig: Rig) -> None:
    rig.mount.sent = Coordinates(rig.mount.ra_at(0.3), -55.0)
    job_id = rig.service.start(PolarOptions(back=False))
    await rig.until(1)
    state = rig.state()
    assert state["options"]["side"] == "west"
    error = state["axis"]
    assert (error["altitude"], error["azimuth"]) == pytest.approx((45, -30), abs=0.05)
    rig.service.finish()
    await rig.jobs.wait(job_id)
    assert len(rig.mount.slews) == 2  # no slew back


async def test_a_frame_not_solved_is_taken_again(rig: Rig) -> None:
    rig.pointing.failures = [SolveError("no stars", Failure.NO_STARS)]
    job_id = rig.service.start(PolarOptions())
    await rig.until(1)
    state = rig.state()
    assert [len(p["failures"]) for p in state["points"]] == [1, 0, 0]
    assert state["points"][0]["failures"][0]["reason"] == "no_stars"
    rig.pointing.failures = [SolveError("no solution", Failure.NO_SOLUTION)]
    await rig.until(3)
    assert [u["failure"] is not None for u in rig.state()["updates"][:3]] == [False, True, False]
    rig.service.finish()
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "succeeded"


async def test_too_many_failures_end_the_run(rig: Rig) -> None:
    rig.pointing.failures = [SolveError("no stars", Failure.NO_STARS)] * 4
    job_id = rig.service.start(PolarOptions())
    await rig.jobs.wait(job_id)
    assert rig.job(job_id)["state"] == "failed"
    assert rig.state()["error"] == "no stars"


async def test_cancel_stops_where_it_is(rig: Rig) -> None:
    job_id = rig.service.start(PolarOptions())
    await rig.until(1)
    rig.jobs.cancel(job_id)
    await rig.jobs.wait(job_id)
    assert rig.state()["state"] == "cancelled"
    assert len(rig.mount.slews) == 2


async def test_a_dec_axis_that_moves_is_warned_about(rig: Rig) -> None:
    rig.pointing.before = {
        1: lambda: setattr(rig.mount, "sent", Coordinates(rig.mount.sent.ra, -57.0))
    }
    job_id = rig.service.start(PolarOptions())
    await rig.until(1)
    assert "Dec axis may have moved" in rig.state()["warning"]
    rig.jobs.cancel(job_id)
    await rig.jobs.wait(job_id)


@pytest.mark.parametrize(
    ("hour_angle", "dec", "options", "message"),
    [
        (-0.5, -85.0, PolarOptions(), "within 10° of the pole"),
        (-0.5, 10.0, PolarOptions(), "would be"),  # low in the east after 60°
        (0.0, -20.0, PolarOptions(side="west"), "tell the two knobs apart"),
        (-10.0, -80.0, PolarOptions(), "under the pole"),
    ],
)
async def test_bad_starts_are_refused(
    rig: Rig, hour_angle: float, dec: float, options: PolarOptions, message: str
) -> None:
    rig.mount.sent = Coordinates(rig.mount.ra_at(hour_angle), dec)
    with pytest.raises(ValueError, match=message):
        rig.service.start(options)
    assert rig.store.get(("polar_alignment",)) is None


async def test_the_horizon_profile_is_respected(rig: Rig) -> None:
    rig.horizon = [HorizonPoint(azimuth=a, altitude=50) for a in (0, 90, 180, 270)]
    with pytest.raises(ValueError, match="under 50°"):
        rig.service.start(PolarOptions())


async def test_refused_without_a_site_or_while_the_mount_is_held(rig: Rig) -> None:
    rig.mount.site_ = None
    with pytest.raises(PointingError, match="site"):
        rig.service.start(PolarOptions())
    rig.mount.site_ = SITE
    token = rig.jobs.reserve("guiding", [Role.MOUNT.value])
    with pytest.raises(ResourceBusyError):
        rig.service.start(PolarOptions())
    rig.jobs.release(token)
    rig.pointing.unavailable = True
    with pytest.raises(SolveError):
        rig.service.start(PolarOptions())


async def test_finish_needs_a_measured_axis(rig: Rig) -> None:
    with pytest.raises(ValueError, match="no polar alignment"):
        rig.service.finish()


def test_options_are_checked() -> None:
    with pytest.raises(ValueError, match="turn"):
        PolarOptions(step=5).check()
    with pytest.raises(ValueError, match="tolerance"):
        PolarOptions(tolerance=0).check()
