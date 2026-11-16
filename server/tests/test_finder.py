"""The Sun and Moon finder against fakes: a mount that points off by an error, a camera
that draws the disc where the body truly is in its frame (ADR 0049)."""

import asyncio
import itertools
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import anyio
import numpy as np
import pytest
from fastapi import HTTPException
from numpy.typing import NDArray
from synthdisc import disc_frame

from nocs.api.finder import stop_phd2
from nocs.api.schemas import FinderState, JobInfo
from nocs.clock import Clock
from nocs.devices import Coordinates, DeviceError, FrameType, Location
from nocs.devices.camera import Range
from nocs.equipment import Role
from nocs.finder import Body, FinderError, FinderOptions, FinderService
from nocs.finder.search import Axes, Offset, aim, offset_between, spiral
from nocs.guiding import GuidingNotReadyError, GuidingService, Phd2Error
from nocs.imaging import Disc, Shot
from nocs.imaging.disc import locate
from nocs.jobs import JobContext, JobManager
from nocs.mount.coords import j2000_to_jnow
from nocs.mount.service import Frame, MountNotReadyError, SunWarningError, local_date, near_sun
from nocs.sky.bodies import position, separation
from nocs.state import StateStore

SITE = Location(-33.5, -70.55, 600.0)
NIGHT = datetime(2026, 11, 15, 1, 0, tzinfo=UTC)
"""The Moon 36° up, the Sun 18° below the horizon."""
DAY = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)
"""The Sun 64° up; the Moon, a young crescent, 41° up near it."""
FIELD = (1.2, 0.8)
"""Degrees."""
SIZE = (480, 320)
"""The frame, pixels."""


class FakeCameraDevice:
    def __init__(self) -> None:
        self.binning = (1, 1)
        self.max_binning = 4
        self.binnings: list[int] = []
        self.exposure_range: Range | None = Range(0.0, 3600.0)

    async def set_binning(self, x: int, y: int | None = None) -> None:
        self.binnings.append(x)
        self.binning = (x, x)


class FakeMount:
    """Says it points where it was sent, while it truly points ``error`` (degrees of RA
    along the axis, and of Dec) away."""

    def __init__(self, jobs: JobManager) -> None:
        self.jobs = jobs
        self.said = Coordinates(3.0, -60.0)
        self.error = (1.5, -1.0)
        self.modes = ["sidereal", "lunar", "solar"]
        self.mode = "sidereal"
        self.refusal: Exception | None = None
        self.near_sun: Coordinates | None = None
        """Slews within 20° of this are refused as near the Sun."""
        self.slews: list[Coordinates] = []
        self.tracking: list[str | None] = []
        self.restored = 0
        self.sync_error: Exception | None = None
        self.syncs: list[tuple[float, float]] = []
        self.hold: anyio.Event | None = None

    @property
    def sky(self) -> Coordinates:
        return Coordinates((self.said.ra + self.error[0] / 15) % 24, self.said.dec + self.error[1])

    def site(self) -> Location | None:
        return SITE

    def position_jnow(self) -> Coordinates:
        return self.said

    def track_modes(self) -> list[str]:
        return self.modes

    def check_goto(
        self, ra: float, dec: float, *, force: bool = False, frame: Frame = "j2000"
    ) -> None:
        if self.refusal is not None:
            raise self.refusal

    async def slew(
        self,
        context: JobContext,
        ra: float,
        dec: float,
        *,
        force: bool = False,
        frame: Frame = "j2000",
        body_rate: bool = False,
    ) -> Coordinates:
        assert frame == "jnow"
        assert body_rate
        assert self.jobs.holder(Role.MOUNT.value) == context.id
        self.check_goto(ra, dec, frame=frame)
        if self.near_sun is not None and separation(Coordinates(ra, dec), self.near_sun) < 20:
            raise SunWarningError("near the Sun")
        await asyncio.sleep(0)
        self.said = Coordinates(ra, dec)
        self.slews.append(self.said)
        return self.said

    async def settle(self, seconds: float) -> None:
        if self.hold is not None:
            await self.hold.wait()
        await asyncio.sleep(0)

    async def track_body(self, mode: str | None, *, job: str) -> None:
        assert self.jobs.holder(Role.MOUNT.value) == job
        self.tracking.append(mode)
        if mode is not None:
            self.mode = mode

    async def restore_rate(self, *, job: str) -> None:
        assert self.jobs.holder(Role.MOUNT.value) == job
        self.restored += 1
        self.mode = "sidereal"

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
        if self.sync_error is not None:
            raise self.sync_error
        self.syncs.append((ra, dec))
        return Coordinates(ra, dec)


class FakeCapture:
    """Draws the body where it is from where the mount truly points, through a camera
    turned ``angle`` degrees (and mirrored), on a sky as bright as ``sky`` at 0.1 s."""

    def __init__(self, jobs: JobManager, mount: FakeMount, clock: Clock, directory: Path) -> None:
        self.jobs = jobs
        self.mount = mount
        self.clock = clock
        self.directory = directory
        self.device = FakeCameraDevice()
        self.body = Body.MOON
        self.angle = 30.0
        self.mirrored = True
        self.sky = 1500.0
        self.phase = 1.0
        self.frames: dict[Path, NDArray[np.uint16]] = {}
        self.exposures: list[float] = []
        self.shown = 0
        self.still = False
        """The disc drawn where it was first seen, whatever the mount does."""
        self.first: Coordinates | None = None
        self.lost_after: int | None = None
        """Frames after which the disc is not drawn any more."""

    def camera(self, role: Role) -> FakeCameraDevice:
        assert role is Role.MAIN_CAMERA
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
        await asyncio.sleep(0)
        self.exposures.append(seconds)
        path = self.directory / f"shot{len(self.exposures)}.fits"
        path.touch()
        self.frames[path] = self.render(seconds)
        return Shot(path, 0, FrameType.LIGHT, self.clock.now(), seconds, None)

    def render(self, seconds: float) -> NDArray[np.uint16]:
        width, height = SIZE
        scale = width / (FIELD[0] * 60)
        body = position(self.body, SITE, self.clock.now())
        sky = self.mount.sky
        if self.still:
            self.first = self.first or sky
            sky = self.first
        seen = offset_between(sky, body.jnow)
        if self.lost_after is not None and len(self.exposures) > self.lost_after:
            seen = Offset(600.0, 600.0)
        a = math.radians(self.angle)
        east, north = seen.east, -seen.north if self.mirrored else seen.north
        dx = (east * math.cos(a) - north * math.sin(a)) * scale
        dy = (east * math.sin(a) + north * math.cos(a)) * scale
        return disc_frame(
            width,
            height,
            x=(width - 1) / 2 + dx,
            y=(height - 1) / 2 + dy,
            radius=body.semidiameter * 60 * scale,
            sky=min(self.sky * seconds / 0.1, 65535.0),
            phase=self.phase,
            angle=200,
        )

    async def disc(self, shot: Shot, radius: float) -> Disc:
        return locate(self.frames[shot.path], color=False, radius=radius * SIZE[0])

    async def show(self, role: Role, shot: Shot) -> None:
        self.shown += 1
        shot.path.unlink()


class Rig:
    def __init__(self, directory: Path, when: datetime = NIGHT) -> None:
        self.store = StateStore()
        self.store.set(
            ("cameras",),
            {"main_camera": {"field": {"width": FIELD[0], "height": FIELD[1]}}},
        )
        self.jobs = JobManager(self.store)
        self.clock = Clock(self.store, system=lambda: when)
        self.mount = FakeMount(self.jobs)
        self.capture = FakeCapture(self.jobs, self.mount, self.clock, directory)
        self.service = FinderService(self.store, self.jobs, self.capture, self.mount, self.clock)

    async def find(self, body: Body = Body.MOON, **options: Any) -> dict[str, Any]:
        self.capture.body = body
        job_id = self.service.start(FinderOptions(body, **options))
        await self.jobs.wait(job_id)
        job = self.store.get(("jobs", job_id))
        assert isinstance(job, dict)
        JobInfo.model_validate(job)
        return job

    def state(self) -> dict[str, Any]:
        state = self.store.get(("finder",))
        assert isinstance(state, dict)
        FinderState.model_validate(state)
        return state

    def synced(self) -> Coordinates:
        """Where the mount was synced, JNow."""
        ra, dec = self.mount.syncs[-1]
        return j2000_to_jnow(ra, dec, self.clock.now())

    def off(self, body: Body = Body.MOON) -> float:
        """Arcminutes from where the mount truly points to the body."""
        return separation(self.mount.sky, position(body, SITE, self.clock.now()).jnow) * 60


# -- Geometry -------------------------------------------------------------------------


def test_aim_and_offset_are_inverse() -> None:
    body = Coordinates(23.9, -20.0)
    point = aim(body, Offset(90.0, -45.0))
    back = offset_between(body, point)
    assert (back.east, back.north) == pytest.approx((90.0, -45.0), abs=1e-6)
    assert point.ra < 1  # past 0h


def test_the_spiral_goes_outwards_around_the_centre() -> None:
    points = spiral(150.0, 50.0)
    assert points[0] == Offset(0.0, 0.0)
    assert len(points) == 1 + 8 + 16 + 12  # rings 1 and 2 whole, ring 3 near its sides
    sizes = [max(abs(p.east), abs(p.north)) for p in points]
    assert sizes == sorted(sizes)
    ring = [p for p in points if max(abs(p.east), abs(p.north)) == 50]
    for a, b in itertools.pairwise(ring):
        assert math.hypot(a.east - b.east, a.north - b.north) == pytest.approx(50)
    assert spiral(0.0, 50.0) == [Offset(0.0, 0.0)]


def test_the_axes_move_the_disc_where_asked() -> None:
    axes = Axes((3.0, 4.0), (-4.0, 3.0))
    move = axes.move(3.0, 4.0)
    assert (move.east, move.north) == pytest.approx((1.0, 0.0))
    assert axes.problem(5.0) is None
    assert axes.problem(20.0) is not None
    assert Axes((3.0, 4.0), (3.0, 4.1)).problem(5.0) is not None


# -- The Sun's warning ------------------------------------------------------------------


def test_near_the_sun_only_while_it_is_up() -> None:
    sun = position(Body.SUN, SITE, DAY).jnow
    assert near_sun(sun, SITE, DAY) == pytest.approx(0.0, abs=0.01)
    assert near_sun(aim(sun, Offset(15 * 60, 0)), SITE, DAY) == pytest.approx(15, abs=0.1)
    assert near_sun(aim(sun, Offset(25 * 60, 0)), SITE, DAY) is None
    night_sun = position(Body.SUN, SITE, NIGHT).jnow
    assert near_sun(night_sun, SITE, NIGHT) is None


def test_the_warning_lasts_until_the_local_date_changes() -> None:
    # Santiago is ~4.7 h behind UTC by the Sun.
    evening = datetime(2026, 11, 16, 4, 0, tzinfo=UTC)
    assert local_date(SITE.longitude, evening).day == 15
    assert local_date(SITE.longitude, evening + timedelta(hours=1)).day == 16


# -- Finding ------------------------------------------------------------------------------


async def test_finds_and_centres_the_moon(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    job = await rig.find()
    assert job["state"] == "succeeded", job
    state = rig.state()
    assert state["state"] == "succeeded"
    assert state["searched"] > 1  # 1.8° off: not in the first frame
    assert rig.off() < 2.0
    assert state["error"] <= 2.0
    assert state["track_mode"] == "lunar"
    assert rig.mount.tracking == ["lunar"]
    assert rig.mount.mode == "lunar"  # kept: the finder succeeded
    assert rig.mount.restored == 0
    assert state["synced"] is True
    moon = position(Body.MOON, SITE, NIGHT).jnow
    # Synced to where it truly points: the Moon, less the centring's last error.
    synced = rig.synced()
    assert separation(synced, rig.mount.sky) * 60 < 0.5
    assert separation(synced, moon) * 60 == pytest.approx(state["error"], abs=0.5)
    # The pointing error, from the body: what the mount missed it by.
    offset = state["offset"]
    assert math.hypot(offset["east"], offset["north"]) == pytest.approx(
        math.hypot(1.5 * math.cos(math.radians(moon.dec)), 1.0) * 60, rel=0.05
    )
    assert rig.capture.device.binnings == [4, 1]  # binned for the frames, then back
    assert rig.capture.shown == state["frames"]
    assert job["result"]["state"] == "succeeded"


async def test_a_body_in_the_first_frame(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    await rig.find(sync=False)
    state = rig.state()
    assert state["searched"] == 1
    assert state["synced"] is False
    assert not rig.mount.syncs
    assert rig.off() < 2.0


async def test_a_crescent_is_centred_on_its_disc(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.capture.phase = 0.25
    rig.capture.mirrored = False
    rig.capture.angle = -70
    rig.mount.error = (-0.6, 0.4)
    await rig.find(tolerance=1.0)
    assert rig.state()["state"] == "succeeded"
    assert rig.off() < 1.5


async def test_from_here(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    moon = position(Body.MOON, SITE, NIGHT).jnow
    # The mount is 6° off, but someone brought the Moon near the middle with the pad.
    rig.mount.error = (6.0, -6.0)
    rig.mount.said = Coordinates((moon.ra - 6.2 / 15) % 24, moon.dec + 5.9)
    await rig.find(here=True, radius=0.0)
    assert rig.state()["state"] == "succeeded"
    assert rig.off() < 2.0


async def test_not_found_within_the_radius(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (8.0, 8.0)
    job = await rig.find(radius=1.0)
    assert job["state"] == "failed"
    state = rig.state()
    assert state["state"] == "failed"
    assert "not within 1°" in state["failure"]
    assert state["searched"] == state["positions"] == 21  # 0.56° steps out to 1°
    assert state["phase"] == "searching"
    assert rig.capture.device.binnings == [4, 1]
    assert rig.mount.restored == 1


async def test_a_bright_sky_is_taken_again_shorter(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    rig.capture.sky = 120000.0  # saturated at 0.1 s
    await rig.find()
    assert rig.capture.exposures[:2] == pytest.approx([0.1, 0.025])
    assert rig.state()["exposure"] == pytest.approx(0.025)
    assert rig.off() < 2.0


async def test_without_lunar_tracking(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.modes = ["sidereal"]
    rig.mount.error = (0.1, 0.1)
    await rig.find()
    state = rig.state()
    assert state["state"] == "succeeded"
    assert state["track_mode"] is None
    assert "no lunar tracking" in state["warning"]
    assert rig.mount.tracking == [None]


async def test_cancelled(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.hold = anyio.Event()
    job_id = rig.service.start(FinderOptions(Body.MOON))
    for _ in range(50):
        await asyncio.sleep(0)
    rig.jobs.cancel(job_id)
    await rig.jobs.wait(job_id)
    assert rig.state()["state"] == "cancelled"
    assert rig.mount.slews  # cancelled while it settled, after binning
    assert rig.capture.device.binnings == [4, 1]
    assert rig.mount.restored == 1
    assert rig.mount.mode == "sidereal"


def test_the_sun_needs_its_warning(tmp_path: Path) -> None:
    rig = Rig(tmp_path, DAY)
    rig.mount.refusal = SunWarningError("the target is 0° from the Sun, near the Sun")
    with pytest.raises(SunWarningError):
        rig.service.start(FinderOptions(Body.SUN))


async def test_finds_the_sun(tmp_path: Path) -> None:
    rig = Rig(tmp_path, DAY)
    rig.capture.sky = 50.0  # behind the filter
    await rig.find(Body.SUN)
    state = rig.state()
    assert state["body"] == "sun"
    assert state["track_mode"] == "solar"
    assert rig.off(Body.SUN) < 2.0


def test_a_body_below_the_horizon(tmp_path: Path) -> None:
    rig = Rig(tmp_path, NIGHT)
    with pytest.raises(FinderError, match="Sun is below the horizon"):
        rig.service.start(FinderOptions(Body.SUN))


def test_a_disc_wider_than_the_field(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.store.set(("cameras", "main_camera", "field"), {"width": 0.6, "height": 0.4})
    with pytest.raises(FinderError, match="does not fit"):
        rig.service.start(FinderOptions(Body.MOON))


def test_no_field(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.store.set(("cameras", "main_camera", "field"), None)
    with pytest.raises(FinderError, match="focal length"):
        rig.service.start(FinderOptions(Body.MOON))


def test_options_are_checked(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    with pytest.raises(ValueError, match="radius"):
        rig.service.start(FinderOptions(Body.MOON, radius=50))
    with pytest.raises(ValueError, match="binning"):
        rig.service.start(FinderOptions(Body.MOON, binning=8))


async def test_places_near_the_sun_are_skipped(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    moon = position(Body.MOON, SITE, NIGHT).jnow
    # As if the Sun were 20.7° west of the Moon, up, and its warning not acknowledged.
    west = 20.7 / 15 / math.cos(math.radians(moon.dec))
    rig.mount.near_sun = Coordinates((moon.ra - west) % 24, moon.dec)
    rig.mount.error = (8.0, 8.0)
    await rig.find(radius=1.0)
    state = rig.state()
    assert state["state"] == "failed"
    assert 0 < state["skipped"] < state["positions"]
    assert "near the Sun were not looked at" in state["failure"]
    assert all(separation(slew, rig.mount.near_sun) >= 20 for slew in rig.mount.slews)


async def test_the_camera_s_shortest_exposure(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    rig.capture.device.exposure_range = Range(0.05, 3600.0)
    rig.capture.sky = 1_000_000.0  # saturated at any exposure: no disc to see
    rig.capture.body = Body.MOON
    await rig.find(radius=0.0)
    assert rig.capture.exposures == pytest.approx([0.1, 0.05])
    assert rig.state()["state"] == "failed"


async def test_a_camera_that_does_not_move_fails_the_axes(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    rig.capture.still = True
    await rig.find()
    state = rig.state()
    assert state["state"] == "failed"
    assert state["phase"] == "calibrating"
    assert "is the mount moving" in state["failure"]
    assert rig.mount.restored == 1
    assert rig.capture.device.binnings == [4, 1]


async def test_the_disc_lost_while_measuring_the_axes(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    rig.capture.lost_after = 1
    await rig.find()
    state = rig.state()
    assert state["state"] == "failed"
    assert "measured the camera's axes" in state["failure"]


async def test_the_disc_lost_while_centring(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.3, 0.2)
    rig.capture.lost_after = 3  # found, then both probes
    await rig.find()
    state = rig.state()
    assert state["state"] == "failed"
    assert state["phase"] == "centring"
    assert "left the frame while centring" in state["failure"]


async def test_out_of_attempts(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.3, 0.2)
    await rig.find(attempts=1, tolerance=0.01)
    state = rig.state()
    assert state["state"] == "failed"
    assert "after 1 moves" in state["failure"]
    assert state["attempts"] == 1


async def test_a_sync_refused_is_a_warning(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (0.1, 0.1)
    rig.mount.sync_error = DeviceError("sync refused")
    await rig.find()
    state = rig.state()
    assert state["state"] == "succeeded"
    assert state["synced"] is False
    assert "sync refused" in state["warning"]


async def test_the_body_low_skips_places_below_the_horizon(tmp_path: Path) -> None:
    low = datetime(2026, 11, 15, 4, 0, tzinfo=UTC)
    assert 0 < position(Body.MOON, SITE, low).alt < 2
    rig = Rig(tmp_path, low)
    rig.mount.error = (8.0, 8.0)
    await rig.find(radius=3.0)
    state = rig.state()
    assert state["state"] == "failed"
    assert len(rig.mount.slews) < state["positions"]


def test_a_search_too_wide_for_the_field(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.store.set(("cameras", "main_camera", "field"), {"width": 0.9, "height": 0.6})
    with pytest.raises(ValueError, match="narrow it"):
        rig.service.start(FinderOptions(Body.MOON, radius=30))


class _Guiding:
    def __init__(self, phd2: object, error: Exception | None = None) -> None:
        self.phd2 = phd2
        self.error = error
        self.stopped = 0

    async def stop(self) -> None:
        self.stopped += 1
        if self.error is not None:
            raise self.error


async def test_finding_the_sun_stops_phd2() -> None:
    guiding = _Guiding(object())
    await stop_phd2(cast(GuidingService, guiding))
    assert guiding.stopped == 1
    # Not there, or not connected to its devices: nothing to stop.
    await stop_phd2(cast(GuidingService, _Guiding(None)))
    await stop_phd2(cast(GuidingService, _Guiding(object(), GuidingNotReadyError("no"))))
    # PHD2 refused: the finder must not start with the guide camera looking at the Sun.
    with pytest.raises(HTTPException) as refused:
        await stop_phd2(cast(GuidingService, _Guiding(object(), Phd2Error("stop_capture", 1, "x"))))
    assert refused.value.status_code == 502


async def test_a_rate_that_cannot_be_put_back_keeps_the_run_s_failure(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.mount.error = (8.0, 8.0)

    async def gone(*, job: str) -> None:
        raise MountNotReadyError("the mount is not connected")

    rig.mount.restore_rate = gone
    await rig.find(radius=0.5)
    state = rig.state()
    assert state["state"] == "failed"
    assert "not within 0.5°" in state["failure"]
    assert rig.capture.device.binnings == [4, 1]
