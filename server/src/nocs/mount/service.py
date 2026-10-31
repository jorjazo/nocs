"""Mount control by role: state, go to, tracking, park, home, time and site, slew pads.

State under ``("mount",)`` while the mount role is ready, ``None`` otherwise::

    {device, ra, dec, ra_j2000, dec_j2000, alt, az, slewing, tracking, track_mode,
     track_modes, parked, parking, can_park, can_home, homing, pier_side, moving,
     moved_by, slew_rate, slew_rates, time, site, site_check, limits}

Go to, park and home run as jobs that lock the mount; cancelling one aborts the
motion. Manual motion goes through slew pads (``nocs.mount.pad``).

Whenever the mount becomes ready, NOCS sends it the site and then the time (as
soon as a client has reported its clock): the lab's ZWO AM7 refuses every go to
after power-on until it gets them, and the site its driver shows is only the
driver's saved configuration (ADR 0015). Go to waits for both.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any, Literal

from nocs.clock import Clock
from nocs.devices import DeviceError, Location, Mount
from nocs.equipment import EquipmentService, Role, Site
from nocs.equipment.service import IndiConnection
from nocs.indi import IndiClient, IndiEvent, PropertyDefined, PropertyUpdated
from nocs.jobs import JobContext, JobManager
from nocs.mount.coords import (
    horizontal_to_jnow,
    j2000_to_jnow,
    jnow_to_horizontal,
    jnow_to_j2000,
)
from nocs.mount.pad import Pad
from nocs.state import Json, Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("mount",)
RESOURCE = Role.MOUNT.value
HORIZON = 0.0
"""Lowest altitude a go to may aim at without ``force``, degrees."""
SITE_TOLERANCE = 0.1
"""Degrees the mount's site may differ from the profile's before NOCS says so."""

type Frame = Literal["j2000", "jnow"]

_WATCHED = frozenset(
    {
        "EQUATORIAL_EOD_COORD",
        "HORIZONTAL_COORD",
        "TELESCOPE_TRACK_STATE",
        "TELESCOPE_TRACK_MODE",
        "TELESCOPE_PARK",
        "TELESCOPE_HOME",
        "TELESCOPE_PIER_SIDE",
        "TELESCOPE_MOTION_NS",
        "TELESCOPE_MOTION_WE",
        "TELESCOPE_SLEW_RATE",
        "TIME_UTC",
        "GEOGRAPHIC_COORD",
        "ALTITUDE_LIMIT_CONTROL",
        "ALTITUDE_LOWER_LIMIT",
        "ALTITUDE_UPPER_LIMIT",
        "MERIDIAN_FLIP",
        "MERIDIAN_LIMIT",
    }
)


class MountNotReadyError(Exception):
    pass


class PointingError(Exception):
    """A go to that NOCS refuses: below the horizon, or the sky position is unknown."""


class MountService:
    def __init__(
        self,
        store: StateStore,
        jobs: JobManager,
        equipment: EquipmentService,
        bridge: IndiConnection,
        clock: Clock,
    ) -> None:
        self._store = store
        self._jobs = jobs
        self._equipment = equipment
        self._clock = clock
        self._client: IndiClient | None = bridge.client
        self._remove_listener = lambda: None
        self._device: str | None = None
        self._published: dict[str, Json] | None = None
        self._pads: set[Pad] = set()
        self._mover: Pad | None = None
        self._site_sent = False
        """The mount got the site since it last became ready."""
        self._time_sent = False
        """The mount got NOCS's time since it last became ready (after the site)."""
        self._tasks: set[asyncio.Task[object]] = set()

        store.set(ROOT, None)
        self._unwatch_bridge = bridge.watch(self._on_client)
        self._unwatch_equipment = equipment.add_listener(self._refresh)
        self._unwatch_clock = clock.add_listener(self._on_clock)
        self._on_client(bridge.client)

    # -- commands ---------------------------------------------------------

    def mount(self) -> Mount:
        if self._client is None or self._device is None:
            raise MountNotReadyError("the mount is not connected")
        return Mount(self._client, self._device)

    def goto(self, ra: float, dec: float, frame: Frame = "j2000", *, force: bool = False) -> str:
        """Slew to equatorial coordinates and track there; returns the job id.

        RA in hours, Dec in degrees. Refused below the horizon when the site and the
        time are known, unless ``force``.
        """
        if not 0 <= ra < 24 or not -90 <= dec <= 90:
            raise ValueError(f"coordinates out of range: RA {ra} h, Dec {dec}°")
        mount = self._ready_to_slew()
        self._require_site_and_time()
        jnow = j2000_to_jnow(ra, dec, self._clock.now()) if frame == "j2000" else None
        self._check_horizon(jnow.ra if jnow else ra, jnow.dec if jnow else dec, force)

        async def run(context: JobContext) -> Json:
            # Converted again at the start: the job may start a moment later.
            target = j2000_to_jnow(ra, dec, self._clock.now()) if frame == "j2000" else None
            to_ra, to_dec = (target.ra, target.dec) if target else (ra, dec)
            context.progress(None, f"slewing to RA {_hms(ra)}, Dec {_dms(dec)}")
            await self._slew(mount, mount.goto(to_ra, to_dec))
            return {"ra": to_ra, "dec": to_dec}

        return self._jobs.start("goto", [RESOURCE], run)

    def goto_horizontal(self, alt: float, az: float) -> str:
        """Point at a place in the local sky (the zenith for flats) and stop tracking there."""
        if not HORIZON <= alt <= 90 or not 0 <= az < 360:
            raise ValueError(f"altitude must be {HORIZON:g}..90° and azimuth 0..360°")
        mount = self._ready_to_slew()
        self._require_site_and_time()
        site = self._site()
        assert site is not None  # the mount got one

        async def run(context: JobContext) -> Json:
            target = horizontal_to_jnow(alt, az, site, self._clock.now())
            context.progress(None, f"slewing to altitude {alt:g}°, azimuth {az:g}°")

            async def slew() -> None:
                await mount.goto(target.ra, target.dec, track=False)
                # Some drivers track after any slew; a fixed point of the sky must not move.
                if mount.tracking:
                    await mount.set_tracking(False)

            await self._slew(mount, slew())
            return {"ra": target.ra, "dec": target.dec}

        return self._jobs.start("goto", [RESOURCE], run)

    async def set_tracking(self, on: bool | None, mode: str | None = None) -> None:
        self._jobs.check_free([RESOURCE])
        mount = self.mount()
        if mode is not None:
            await mount.set_track_mode(mode)
        if on is not None:
            if on and mount.parked:
                raise ValueError(f"{mount.name} is parked")
            await mount.set_tracking(on)

    def park(self) -> str:
        mount = self.mount()
        if not mount.can_park:
            raise DeviceError(f"{mount.name} cannot park")
        self._jobs.check_free([RESOURCE])

        async def run(context: JobContext) -> Json:
            context.progress(None, "parking")
            await self._slew(mount, mount.park())
            return None

        return self._jobs.start("park", [RESOURCE], run)

    async def unpark(self) -> None:
        self._jobs.check_free([RESOURCE])
        await self.mount().unpark()

    def home(self) -> str:
        mount = self._ready_to_slew()
        if not mount.can_home:
            raise DeviceError(f"{mount.name} cannot go home")

        async def run(context: JobContext) -> Json:
            context.progress(None, "going home")
            await self._slew(mount, mount.home())
            return None

        return self._jobs.start("home", [RESOURCE], run)

    async def abort(self) -> None:
        """Stop everything the mount is doing, whoever started it."""
        for pad in list(self._pads):
            pad.interrupt("the mount was stopped")
        job = self._jobs.job_holding(RESOURCE)
        if job is not None:
            self._jobs.cancel(job)  # the job aborts the slew itself as well
        await self.mount().abort()

    async def send_time(self) -> None:
        """Set the mount's clock from the time NOCS trusts."""
        if not self._clock.known:
            raise PointingError("the time is unknown until a client reports its clock")
        await self.mount().set_time(self._clock.now(), self._clock.utc_offset or 0.0)
        self._time_sent = True
        self._publish()

    async def send_site(self, site: Site | None = None) -> None:
        """Set the mount's site (the one given, or the usual one) and then its time again."""
        self._jobs.check_free([RESOURCE])
        await self._send_site(_location(site) if site is not None else None)
        if self._clock.known:
            await self.send_time()

    def pad(self, client: str) -> Pad:
        """A slew pad for one client; ``close_pad`` when the client is gone."""
        pad = Pad(self, client)
        self._pads.add(pad)
        return pad

    def close_pad(self, pad: Pad) -> None:
        self._pads.discard(pad)

    async def close(self) -> None:
        self._unwatch_bridge()
        self._unwatch_equipment()
        self._unwatch_clock()
        self._remove_listener()
        for pad in list(self._pads):
            await pad.stop("nocsd is stopping")
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks)

    # -- PadHost ------------------------------------------------------------

    def reserve(self, pad: Pad) -> str:
        token = self._jobs.reserve("move", [RESOURCE])
        self._mover = pad
        self._publish()
        return token

    def release(self, pad: Pad, token: str) -> None:
        self._jobs.release(token)
        if self._mover is pad:
            self._mover = None
        self._publish()

    # -- internals: commands ------------------------------------------------

    async def _send_site(self, location: Location | None = None) -> None:
        """Send ``location``, or the profile's site, or else what the driver has saved."""
        location = location or self._site()
        if location is None:
            raise PointingError("the site is unknown: set it in the profile")
        await self.mount().set_location(location)
        self._site_sent = True
        self._publish()

    def _require_site_and_time(self) -> None:
        if not self._site_sent:
            raise PointingError(
                "the mount has not received the site yet: set it in the profile, or connect again"
            )
        if not self._time_sent:
            raise PointingError(
                "the mount has not received the time yet: a client must report its clock first"
            )

    def _ready_to_slew(self) -> Mount:
        mount = self.mount()
        if mount.parked:
            raise ValueError(f"{mount.name} is parked: unpark it first")
        self._jobs.check_free([RESOURCE])
        return mount

    async def _slew(self, mount: Mount, motion: Coroutine[Any, Any, None]) -> None:
        """Run a slew; if the job is cancelled, abort the motion before giving up."""
        try:
            await motion
        except asyncio.CancelledError:
            try:
                await asyncio.shield(mount.abort())
            except (DeviceError, ConnectionError) as e:
                log.error("%s: abort after cancelling failed: %s", mount.name, e)
            raise

    def _check_horizon(self, ra: float, dec: float, force: bool) -> None:
        site = self._site()
        if force or site is None or not self._clock.known:
            return
        altitude = jnow_to_horizontal(ra, dec, site, self._clock.now()).alt
        if altitude < HORIZON:
            raise PointingError(
                f"the target is {-altitude:.1f}° below the horizon; force the go to to slew anyway"
            )

    def _site(self) -> Location | None:
        """Where the rig is: the profile's site, or else the mount's."""
        profile = self._equipment.active_profile
        if profile is not None and profile.site is not None:
            return _location(profile.site)
        if self._device is None or self._client is None:
            return None
        return Mount(self._client, self._device).location

    # -- internals: state -------------------------------------------------

    def _on_client(self, client: IndiClient | None) -> None:
        self._remove_listener()
        self._remove_listener = lambda: None
        self._client = client
        if client is not None:
            self._remove_listener = client.add_listener(self._on_event)
        self._refresh()

    def _refresh(self) -> None:
        """Follow the mount role as the equipment connects and disconnects."""
        name = self._equipment.ready_device(Role.MOUNT) if self._client is not None else None
        if name == self._device:
            self._publish()  # the profile (site) may have changed
            return
        self._device = name
        self._published = None
        self._site_sent = False
        self._time_sent = False
        if name is None:
            self._store.set(ROOT, None)
            return
        self._publish()
        self._background(self._on_ready())

    async def _on_ready(self) -> None:
        mount = self.mount()
        if mount.motion.moving and self._mover is None:
            # Left moving by a nocsd that stopped mid-move, or by another client.
            log.warning("%s was moving with nobody at a pad: stopping it", mount.name)
            try:
                await mount.stop()
            except (DeviceError, ConnectionError) as e:
                log.error("%s: stop failed (%s); aborting", mount.name, e)
                try:
                    await mount.abort()
                except (DeviceError, ConnectionError) as e2:
                    log.critical("%s may still be moving: %s", mount.name, e2)
        await self._send_site_and_time()

    def _on_clock(self) -> None:
        self._publish()
        if self._device is not None and not self._time_sent:
            self._background(self._send_site_and_time())

    async def _send_site_and_time(self) -> None:
        """Site first, then time (the order EKOS uses); failures are only logged."""
        try:
            if not self._site_sent:
                await self._send_site()
            if self._clock.known and not self._time_sent:
                await self.send_time()
        except (DeviceError, ConnectionError, MountNotReadyError, PointingError) as e:
            log.warning("could not send the mount its site and time: %s", e)

    def _on_event(self, event: IndiEvent) -> None:
        match event:
            case PropertyUpdated(property=prop) | PropertyDefined(property=prop) if (
                prop.device == self._device and prop.name in _WATCHED
            ):
                self._publish()
            case _:
                pass

    def _publish(self) -> None:
        if self._device is None or self._client is None:
            return
        try:
            summary = self._summary(Mount(self._client, self._device))
        except (DeviceError, KeyError, TypeError) as e:
            log.debug("mount not publishable yet: %s", e)
            return
        previous = self._published
        if previous is None:
            self._store.set(ROOT, summary)
        else:
            changed = {k: v for k, v in summary.items() if previous.get(k) != v}
            if not changed:
                return
            with self._store.transaction():
                for key, value in changed.items():
                    self._store.set((*ROOT, key), value)
        self._published = summary

    def _summary(self, mount: Mount) -> dict[str, Json]:
        now = self._clock.now()
        position = mount.coordinates
        j2000 = jnow_to_j2000(position.ra, position.dec, now)
        horizontal = mount.horizontal
        site = self._site()
        if horizontal is None and site is not None and self._clock.known:
            horizontal = jnow_to_horizontal(position.ra, position.dec, site, now)
        motion = mount.motion
        mount_site = mount.location
        mount_time = mount.time
        altitude = mount.altitude_limits
        meridian = mount.meridian_limits
        return {
            "device": mount.name,
            "ra": position.ra,
            "dec": position.dec,
            "ra_j2000": j2000.ra,
            "dec_j2000": j2000.dec,
            "alt": horizontal.alt if horizontal else None,
            "az": horizontal.az if horizontal else None,
            "slewing": mount.slewing,
            "tracking": mount.tracking,
            "track_mode": mount.track_mode,
            "track_modes": list[Json](mount.track_modes),
            "parked": mount.parked,
            "parking": mount.parking,
            "can_park": mount.can_park,
            "can_home": mount.can_home,
            "homing": mount.homing,
            "pier_side": mount.pier_side.value,
            "moving": {
                "ns": motion.ns.value if motion.ns else None,
                "we": motion.we.value if motion.we else None,
            },
            "moved_by": self._mover.client if self._mover is not None else None,
            "slew_rate": mount.slew_rate,
            "slew_rates": list[Json](mount.slew_rates),
            "time": mount_time.isoformat(timespec="seconds") if mount_time else None,
            "site": (
                {
                    "latitude": mount_site.latitude,
                    "longitude": mount_site.longitude,
                    "elevation": mount_site.elevation,
                }
                if mount_site
                else None
            ),
            "site_check": self._site_check(mount_site),
            "site_sent": self._site_sent,
            "time_sent": self._time_sent,
            "limits": {
                "altitude": (
                    {"enabled": altitude.enabled, "lower": altitude.lower, "upper": altitude.upper}
                    if altitude
                    else None
                ),
                "meridian": (
                    {"flip": meridian.flip, "limit": meridian.limit} if meridian else None
                ),
            },
        }

    def _site_check(self, mount_site: Location | None) -> str:
        profile = self._equipment.active_profile
        if profile is None or profile.site is None:
            return "no_profile_site"
        if mount_site is None:
            return "unknown"
        site = profile.site
        longitude = abs((site.longitude - mount_site.longitude + 180) % 360 - 180)
        if abs(site.latitude - mount_site.latitude) > SITE_TOLERANCE or (
            longitude > SITE_TOLERANCE
        ):
            return "different"
        return "same"

    def _background(self, coro: Coroutine[Any, Any, object]) -> None:
        task: asyncio.Task[object] = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # keep a reference until it is done
        task.add_done_callback(self._tasks.discard)


def _location(site: Site) -> Location:
    return Location(site.latitude, site.longitude, site.elevation)


def _hms(hours: float) -> str:
    total = round(hours * 3600)
    return f"{total // 3600:02d}h{total // 60 % 60:02d}m{total % 60:02d}s"


def _dms(degrees: float) -> str:
    total = round(abs(degrees) * 3600)
    sign = "-" if degrees < 0 else "+"
    return f"{sign}{total // 3600:02d}°{total // 60 % 60:02d}'{total % 60:02d}\""
