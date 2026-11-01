"""Mount facade, coordinates, the client clock and the slew pad, against fakes."""

import asyncio
import math
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import astropy.coordinates  # pyright: ignore[reportMissingTypeStubs]
import astropy.time  # pyright: ignore[reportMissingTypeStubs]
import astropy.units  # pyright: ignore[reportMissingTypeStubs]
import pytest
from fakes import FakeClient, driver_info, switch_property

from nocs.clock import Clock
from nocs.devices import (
    STOPPED,
    DeviceError,
    DeviceInterface,
    Direction,
    Location,
    Motion,
    Mount,
)
from nocs.indi import Property, PropertyState, PropertyType
from nocs.indi.properties import NumberElement, TextElement
from nocs.jobs import JobManager, ResourceBusyError
from nocs.mount.coords import (
    horizontal_to_jnow,
    j2000_to_jnow,
    jnow_to_horizontal,
    jnow_to_j2000,
)
from nocs.mount.pad import Pad, PadCommand, PadStatus, drive
from nocs.state import StateStore

NAME = "Mount"
NORTH = Motion(ns=Direction.NORTH)
SITE = Location(-30.03, -70.65, 1000)  # the maintainer's site, Diaguitas


def define_mount(client: FakeClient) -> None:
    client.define(driver_info(NAME, DeviceInterface.TELESCOPE))
    coords = Property(NAME, "EQUATORIAL_EOD_COORD", PropertyType.NUMBER, state=PropertyState.OK)
    for key, value in {"RA": 6.0, "DEC": -90.0}.items():
        coords.elements[key] = NumberElement(key, key, value, max=360, min=-90)
    client.define(coords)
    client.define(switch_property(NAME, "ON_COORD_SET", TRACK=True, SLEW=False, SYNC=False))
    client.define(switch_property(NAME, "TELESCOPE_PARK", PARK=False, UNPARK=True))
    client.define(
        switch_property(NAME, "TELESCOPE_MOTION_NS", MOTION_NORTH=False, MOTION_SOUTH=False)
    )
    client.define(
        switch_property(NAME, "TELESCOPE_MOTION_WE", MOTION_WEST=False, MOTION_EAST=False)
    )
    client.define(switch_property(NAME, "TELESCOPE_SLEW_RATE", **{"1x": False, "2x": True}))
    client.define(switch_property(NAME, "TELESCOPE_ABORT_MOTION", ABORT=False))
    client.define(
        switch_property(
            NAME, "TELESCOPE_TRACK_MODE", TRACK_SIDEREAL=True, TRACK_SOLAR=False, TRACK_LUNAR=False
        )
    )
    time_prop = Property(NAME, "TIME_UTC", PropertyType.TEXT, state=PropertyState.OK)
    time_prop.elements["UTC"] = TextElement("UTC", "UTC", "2000-01-01T02:05:04")
    time_prop.elements["OFFSET"] = TextElement("OFFSET", "Offset", "0.00")
    client.define(time_prop)
    site = Property(NAME, "GEOGRAPHIC_COORD", PropertyType.NUMBER, state=PropertyState.OK)
    for key, value in {"LAT": -30.03, "LONG": 289.35, "ELEV": 0.0}.items():
        site.elements[key] = NumberElement(key, key, value, min=-90, max=360)
    client.define(site)


ACKNOWLEDGED = ("TELESCOPE_SLEW_RATE", "TIME_UTC", "GEOGRAPHIC_COORD", "TELESCOPE_TRACK_MODE")


class MotionDriver:
    """Answers manual motion as INDI's Telescope base class does."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.refuse = False
        self.fail_stop = False
        self.aborted = 0
        self.tracking = False
        """Whether the simulated mount really tracks, whatever its switch says."""

    def __call__(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        update = self.client.update
        if name in ("TELESCOPE_MOTION_NS", "TELESCOPE_MOTION_WE"):
            on = [k for k, v in values.items() if v]
            if not on:
                state = PropertyState.ALERT if self.fail_stop else PropertyState.IDLE
                loop.call_soon(update, device, name, state, _off(values))
            elif self.refuse:
                loop.call_soon(update, device, name, PropertyState.IDLE, _off(values))
            else:
                loop.call_soon(update, device, name, PropertyState.BUSY, _str(values))
        elif name == "TELESCOPE_ABORT_MOTION":
            self.aborted += 1
            for axis in ("TELESCOPE_MOTION_NS", "TELESCOPE_MOTION_WE"):
                prop = self.client.get_property(device, axis)
                assert prop is not None
                off = {k: "Off" for k in prop.elements}
                loop.call_soon(update, device, axis, PropertyState.IDLE, off)
            loop.call_soon(update, device, name, PropertyState.OK, {"ABORT": "Off"})
        elif name in (
            "TELESCOPE_SLEW_RATE",
            "TIME_UTC",
            "GEOGRAPHIC_COORD",
            "TELESCOPE_TRACK_MODE",
        ):
            loop.call_soon(update, device, name, PropertyState.OK, _str(values))
        elif name == "TELESCOPE_TRACK_STATE":
            # As INDI's Telescope base class: a request that matches the switch as it
            # stands changes nothing, even when the mount itself is not tracking.
            prop = self.client.get_property(device, name)
            assert prop is not None
            if prop.switch("TRACK_ON") != values["TRACK_ON"]:
                self.tracking = bool(values["TRACK_ON"])
            state = PropertyState.BUSY if values["TRACK_ON"] else PropertyState.IDLE
            loop.call_soon(update, device, name, state, _str(values))


def _str(values: Mapping[str, str | float | bool]) -> dict[str, str]:
    return {k: ("On" if v else "Off") if isinstance(v, bool) else str(v) for k, v in values.items()}


def _off(values: Mapping[str, str | float | bool]) -> dict[str, str]:
    return {k: "Off" for k in values}


@pytest.fixture
def client() -> FakeClient:
    client = FakeClient()
    define_mount(client)
    return client


@pytest.fixture
def driver(client: FakeClient) -> MotionDriver:
    driver = MotionDriver(client)
    client.responder = driver
    return driver


# -- facade -------------------------------------------------------------------


def test_reads(client: FakeClient) -> None:
    mount = Mount(client, NAME)
    assert mount.motion == STOPPED
    assert mount.slew_rates == ["1x", "2x"]
    assert mount.slew_rate == "2x"
    assert mount.slew_rate_labels == ["1x", "2x"]
    assert mount.track_modes == ["sidereal", "solar", "lunar"]
    assert mount.track_mode == "sidereal"
    assert mount.location == Location(-30.03, pytest.approx(-70.65), 0.0)  # pyright: ignore[reportArgumentType]
    assert mount.time == datetime(2000, 1, 1, 2, 5, 4, tzinfo=UTC)
    assert mount.horizontal is None
    assert mount.altitude_limits is None
    assert not mount.can_home


async def test_move_and_stop(client: FakeClient, driver: MotionDriver) -> None:
    mount = Mount(client, NAME)
    await mount.move(Motion(Direction.NORTH, Direction.EAST))
    assert mount.motion == Motion(Direction.NORTH, Direction.EAST)
    client.sent.clear()
    await mount.move(Motion(we=Direction.EAST))
    assert client.sent == [
        (NAME, "TELESCOPE_MOTION_NS", {"MOTION_NORTH": False, "MOTION_SOUTH": False})
    ]
    await mount.stop()
    assert mount.motion == STOPPED


async def test_reversing_stops_first(client: FakeClient, driver: MotionDriver) -> None:
    mount = Mount(client, NAME)
    await mount.move(NORTH)
    client.sent.clear()
    await mount.move(Motion(ns=Direction.SOUTH))
    assert [values for _, _, values in client.sent] == [
        {"MOTION_NORTH": False, "MOTION_SOUTH": False},
        {"MOTION_NORTH": False, "MOTION_SOUTH": True},
    ]


async def test_refused_motion_is_an_error(client: FakeClient, driver: MotionDriver) -> None:
    driver.refuse = True
    with pytest.raises(DeviceError, match="refused to move north"):
        await Mount(client, NAME).move(NORTH)


async def test_parked_mount_does_not_move(client: FakeClient, driver: MotionDriver) -> None:
    client.update(NAME, "TELESCOPE_PARK", PropertyState.OK, {"PARK": "On", "UNPARK": "Off"})
    with pytest.raises(ValueError, match="parked"):
        await Mount(client, NAME).move(NORTH)
    assert client.sent == []


async def test_time_and_site(client: FakeClient, driver: MotionDriver) -> None:
    mount = Mount(client, NAME)
    await mount.set_time(datetime(2026, 10, 30, 23, 10, 5, 600000, tzinfo=UTC), -3)
    await mount.set_location(Location(-30.03, -70.65, 1100))
    assert client.sent[0] == (NAME, "TIME_UTC", {"UTC": "2026-10-30T23:10:05", "OFFSET": "-3.00"})
    assert client.sent[1][2] == {"LAT": -30.03, "LONG": pytest.approx(289.35), "ELEV": 1100}


async def test_slew_rate_and_track_mode(client: FakeClient, driver: MotionDriver) -> None:
    mount = Mount(client, NAME)
    await mount.set_slew_rate("1x")
    assert mount.slew_rate == "1x"
    with pytest.raises(ValueError, match="no slew rate 9x"):
        await mount.set_slew_rate("9x")
    await mount.set_track_mode("lunar")
    assert mount.track_mode == "lunar"


async def test_tracking_on_after_an_abort_is_a_real_change(
    client: FakeClient, driver: MotionDriver
) -> None:
    """Right after an abort the switch may still say on while the mount has stopped."""
    client.define(switch_property(NAME, "TELESCOPE_TRACK_STATE", TRACK_ON=True, TRACK_OFF=False))
    client.update(NAME, "EQUATORIAL_EOD_COORD", PropertyState.IDLE)
    mount = Mount(client, NAME)
    await mount.set_tracking(True)
    assert driver.tracking
    assert mount.tracking
    assert [v for _, n, v in client.sent if n == "TELESCOPE_TRACK_STATE"] == [
        {"TRACK_ON": False, "TRACK_OFF": True},
        {"TRACK_ON": True, "TRACK_OFF": False},
    ]

    # While it tracks (coordinates Ok), asking again is just one request.
    driver.tracking = True
    client.update(NAME, "EQUATORIAL_EOD_COORD", PropertyState.OK)
    client.sent.clear()
    await mount.set_tracking(True)
    assert [n for _, n, _ in client.sent] == ["TELESCOPE_TRACK_STATE"]
    await mount.set_tracking(False)
    assert not driver.tracking
    assert not mount.tracking


# -- coordinates --------------------------------------------------------------

WHEN = datetime(2026, 10, 30, 22, 0, tzinfo=UTC)


# Untyped library, as in nocs.storage.fits: used through untyped handles.
_coords: Any = astropy.coordinates
_units: Any = astropy.units
_time: Any = astropy.time


def astropy_altaz(ra: float, dec: float) -> tuple[float, float]:
    deg, m = _units.deg, _units.m
    location = _coords.EarthLocation(
        lat=SITE.latitude * deg, lon=SITE.longitude * deg, height=SITE.elevation * m
    )
    frame = _coords.AltAz(obstime=_time.Time(WHEN), location=location)
    altaz = _coords.SkyCoord(ra=ra * 15 * deg, dec=dec * deg).transform_to(frame)
    return float(altaz.alt.deg), float(altaz.az.deg)


@pytest.mark.parametrize(("ra", "dec"), [(0.712305, 41.26875), (5.919529, 7.407064), (18.6, -60)])
def test_j2000_round_trip_and_altaz_match_astropy(ra: float, dec: float) -> None:
    jnow = j2000_to_jnow(ra, dec, WHEN)
    back = jnow_to_j2000(jnow.ra, jnow.dec, WHEN)
    assert back.ra == pytest.approx(ra, abs=1e-7)
    assert back.dec == pytest.approx(dec, abs=1e-6)
    # Precession over 26 years moves objects by about 20 arcminutes.
    assert 0.05 < abs(jnow.ra - ra) * 15 + abs(jnow.dec - dec) < 1
    alt, az = astropy_altaz(ra, dec)
    horizontal = jnow_to_horizontal(jnow.ra, jnow.dec, SITE, WHEN)
    arcsec = 1 / 3600
    assert horizontal.alt == pytest.approx(alt, abs=2 * arcsec)
    assert horizontal.az == pytest.approx(az, abs=2 * arcsec / math.cos(math.radians(alt)))


def test_zenith_is_at_the_site_latitude() -> None:
    zenith = horizontal_to_jnow(90, 0, SITE, WHEN)
    assert zenith.dec == pytest.approx(SITE.latitude, abs=1e-6)
    back = jnow_to_horizontal(zenith.ra, zenith.dec, SITE, WHEN)
    assert back.alt == pytest.approx(90, abs=1e-6)


# -- clock --------------------------------------------------------------------


class Ticks:
    def __init__(self) -> None:
        self.system = datetime(2026, 10, 30, 23, 0, tzinfo=UTC)
        self.monotonic = 100.0

    def advance(self, seconds: float) -> None:
        self.system += timedelta(seconds=seconds)
        self.monotonic += seconds


def test_clock_trusts_the_system_until_it_is_off() -> None:
    store, ticks = StateStore(), Ticks()
    clock = Clock(store, system=lambda: ticks.system, monotonic=lambda: ticks.monotonic)
    assert (clock.known, clock.offset, clock.now()) == (False, None, ticks.system)

    assert clock.report(ticks.system + timedelta(seconds=2)) == pytest.approx(2)
    assert not clock.corrected
    assert clock.correction == 0
    assert clock.now() == ticks.system

    client = ticks.system + timedelta(hours=3)
    clock.report(client, utc_offset=-3)
    assert clock.corrected
    assert clock.correction == pytest.approx(3 * 3600)
    assert store.get(("clock", "corrected")) is True
    ticks.advance(60)
    assert clock.now() == client + timedelta(seconds=60)
    assert clock.utc_offset == -3


def test_clock_follows_a_later_fix_of_the_system_clock() -> None:
    ticks = Ticks()
    clock = Clock(StateStore(), system=lambda: ticks.system, monotonic=lambda: ticks.monotonic)
    right = ticks.system + timedelta(days=2)
    clock.report(right)
    ticks.system = right  # e.g. NTP got through
    ticks.advance(10)
    assert clock.offset == pytest.approx(0)
    assert not clock.corrected
    assert clock.now() == right + timedelta(seconds=10)


def test_clock_needs_a_time_zone() -> None:
    with pytest.raises(ValueError, match="time zone"):
        Clock(StateStore()).report(datetime(2026, 10, 30, 23, 0))


# -- reservations -------------------------------------------------------------


async def test_reservation_locks_like_a_job() -> None:
    store = StateStore()
    jobs = JobManager(store)
    token = jobs.reserve("move", ["mount"])
    with pytest.raises(ResourceBusyError, match=r"mount is busy \(move\)") as error:
        jobs.start("goto", ["mount"], lambda _: asyncio.sleep(0))  # pyright: ignore[reportArgumentType]
    assert error.value.job_id is None
    assert jobs.job_holding("mount") is None
    assert store.get(("jobs",)) == {}
    jobs.release(token)
    jobs.release(token)
    assert jobs.holder("mount") is None


# -- slew pad -----------------------------------------------------------------


class Host:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.jobs = JobManager(StateStore())
        self.ready = True

    def mount(self) -> Mount:
        if not self.ready:
            raise RuntimeError("the mount is not connected")
        return Mount(self.client, NAME)

    def reserve(self, pad: Pad) -> str:
        return self.jobs.reserve("move", ["mount"])

    def release(self, pad: Pad, token: str) -> None:
        self.jobs.release(token)


class Client:
    """A pad client: commands go in a stream; ``None`` closes the connection."""

    def __init__(self) -> None:
        self.send_in, self.receive_in = anyio.create_memory_object_stream[PadCommand | None | str](
            10
        )
        self.statuses: list[PadStatus] = []

    async def receive(self) -> PadCommand | None:
        item = await self.receive_in.receive()
        if isinstance(item, str):
            raise ValueError(item)
        return item

    async def send(self, status: PadStatus) -> None:
        self.statuses.append(status)


async def wait_until(condition: Callable[[], bool], timeout: float = 2) -> None:
    """Poll a condition on the fake driver, which offers nothing to wait on."""
    with anyio.fail_after(timeout):
        while not condition():  # noqa: ASYNC110
            await anyio.sleep(0.01)


async def test_pad_moves_while_held_and_stops_when_let_go(
    client: FakeClient, driver: MotionDriver
) -> None:
    host, user = Host(client), Client()
    pad = Pad(host, "phone")
    mount = Mount(client, NAME)
    async with anyio.create_task_group() as group:
        group.start_soon(drive, pad, user.receive, user.send, 0.3)
        for _ in range(5):  # keepalives, well inside the timeout
            await user.send_in.send(PadCommand(NORTH, "1x"))
            await anyio.sleep(0.1)
        assert mount.motion == NORTH
        assert mount.slew_rate == "1x"
        assert host.jobs.holder("mount") is not None
        await user.send_in.send(PadCommand(STOPPED))
        await wait_until(lambda: mount.motion == STOPPED)
        await wait_until(lambda: host.jobs.holder("mount") is None)
        await user.send_in.send(None)
    assert not user.statuses[-1].latched


def test_the_am5_names_its_rates_by_index() -> None:
    client = FakeClient()
    client.replay("lab-rig-2026-10-30.xml", "ZWO AM5")
    mount = Mount(client, "ZWO AM5")
    assert mount.slew_rates[-1] == "10x"
    assert mount.slew_rate_labels == [
        "0.25x", "0.5x", "1x", "2x", "4x", "8x", "20x", "60x", "720x", "1440x"
    ]  # fmt: skip


async def test_pad_sends_the_rate_at_every_start(client: FakeClient, driver: MotionDriver) -> None:
    # The AM5's driver shows 1440x On without having sent it: the switch says
    # nothing about the mount, so the rate goes out even when it matches.
    host, user = Host(client), Client()
    pad = Pad(host, "phone")
    mount = Mount(client, NAME)

    def rates() -> int:
        return sum(1 for _, name, _ in client.sent if name == "TELESCOPE_SLEW_RATE")

    async with anyio.create_task_group() as group:
        group.start_soon(drive, pad, user.receive, user.send, 0.3)
        for _ in range(2):
            for _ in range(3):  # a press and its keepalives
                await user.send_in.send(PadCommand(NORTH, "2x"))
                await anyio.sleep(0.05)
            await user.send_in.send(PadCommand(STOPPED))
            await wait_until(lambda: mount.motion == STOPPED)
        await user.send_in.send(None)
    assert mount.slew_rate == "2x"
    assert rates() == 2


async def test_dead_man_stops_on_silence_and_latches(
    client: FakeClient, driver: MotionDriver
) -> None:
    host, user = Host(client), Client()
    pad = Pad(host, "phone")
    mount = Mount(client, NAME)
    async with anyio.create_task_group() as group:
        group.start_soon(drive, pad, user.receive, user.send, 0.3)
        await user.send_in.send(PadCommand(NORTH))
        await wait_until(lambda: mount.motion == NORTH)
        started = anyio.current_time()
        # The client goes silent (Wi-Fi gone) with the button still down.
        await wait_until(lambda: mount.motion == STOPPED)
        assert 0.25 < anyio.current_time() - started < 0.6
        assert user.statuses[-1].latched
        assert "no word from phone" in (user.statuses[-1].message or "")
        assert host.jobs.holder("mount") is None

        # It comes back still holding: the pad does not resume until let go.
        await user.send_in.send(PadCommand(NORTH))
        await anyio.sleep(0.05)
        assert mount.motion == STOPPED
        assert "let go" in (user.statuses[-1].message or "")
        await user.send_in.send(PadCommand(STOPPED))
        await user.send_in.send(PadCommand(NORTH))
        await wait_until(lambda: mount.motion == NORTH)
        group.cancel_scope.cancel()
    # Cancelled (nocsd stopping, socket handler gone): stopped on the way out.
    assert mount.motion == STOPPED
    assert host.jobs.holder("mount") is None


async def test_closing_the_connection_stops(client: FakeClient, driver: MotionDriver) -> None:
    host, user = Host(client), Client()
    mount = Mount(client, NAME)
    async with anyio.create_task_group() as group:
        group.start_soon(drive, Pad(host, "phone"), user.receive, user.send, 5)
        await user.send_in.send(PadCommand(Motion(Direction.SOUTH, Direction.WEST)))
        await wait_until(lambda: mount.motion.moving)
        await user.send_in.send(None)
    assert mount.motion == STOPPED


async def test_bad_message_stops(client: FakeClient, driver: MotionDriver) -> None:
    host, user = Host(client), Client()
    mount = Mount(client, NAME)
    async with anyio.create_task_group() as group:
        group.start_soon(drive, Pad(host, "phone"), user.receive, user.send, 5)
        await user.send_in.send(PadCommand(NORTH))
        await wait_until(lambda: mount.motion == NORTH)
        await user.send_in.send("not json")
        await wait_until(lambda: mount.motion == STOPPED)
        await user.send_in.send(None)
    assert "bad message" in (user.statuses[-1].message or "")


async def test_failed_stop_aborts(client: FakeClient, driver: MotionDriver) -> None:
    host = Host(client)
    mount = Mount(client, NAME)
    pad = Pad(host, "phone")
    await pad.apply(PadCommand(NORTH))
    driver.fail_stop = True
    await pad.apply(PadCommand(STOPPED))
    assert driver.aborted == 1
    assert mount.motion == STOPPED
    assert host.jobs.holder("mount") is None


async def test_pad_refused_while_the_mount_is_busy(
    client: FakeClient, driver: MotionDriver
) -> None:
    host = Host(client)
    host.jobs.reserve("goto", ["mount"])
    status = await Pad(host, "phone").apply(PadCommand(NORTH))
    assert status.latched
    assert "busy" in (status.message or "")
    assert Mount(client, NAME).motion == STOPPED


async def test_interrupt_latches_and_frees_the_mount(
    client: FakeClient, driver: MotionDriver
) -> None:
    host = Host(client)
    pad = Pad(host, "phone")
    await pad.apply(PadCommand(NORTH))
    await Mount(client, NAME).abort()
    pad.interrupt("the mount was stopped")
    assert host.jobs.holder("mount") is None
    status = await pad.apply(PadCommand(NORTH))
    assert status.latched
    assert Mount(client, NAME).motion == STOPPED
