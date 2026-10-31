from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from nocs.devices.base import DEFAULT_TIMEOUT, Device, DeviceError, DeviceInterface
from nocs.indi import Property, PropertyState

SLEW_TIMEOUT = 300.0
MOTION_TIMEOUT = 2.0
"""Drivers answer a start or stop of manual motion at once; the pad cannot wait longer."""


@dataclass(frozen=True, slots=True)
class Coordinates:
    """Equatorial coordinates of the current epoch (JNow): RA in hours, Dec in degrees."""

    ra: float
    dec: float


@dataclass(frozen=True, slots=True)
class Horizontal:
    """Altitude and azimuth (north = 0°, east = 90°), degrees."""

    alt: float
    az: float


@dataclass(frozen=True, slots=True)
class Location:
    """Where the mount thinks it is: degrees (east positive, -180..180) and metres."""

    latitude: float
    longitude: float
    elevation: float


@dataclass(frozen=True, slots=True)
class AltitudeLimits:
    enabled: bool
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class MeridianLimits:
    flip: bool
    """The mount flips by itself when it reaches the limit."""
    limit: float
    """Degrees past the meridian (as the driver defines it)."""


class PierSide(StrEnum):
    EAST = "east"
    WEST = "west"
    UNKNOWN = "unknown"


class Direction(StrEnum):
    NORTH = "north"
    SOUTH = "south"
    WEST = "west"
    EAST = "east"


@dataclass(frozen=True, slots=True)
class Motion:
    """Manual motion on each axis; ``None`` when that axis is not moving."""

    ns: Direction | None = None
    we: Direction | None = None

    def __post_init__(self) -> None:
        if self.ns not in (None, Direction.NORTH, Direction.SOUTH):
            raise ValueError(f"{self.ns} is not a north-south direction")
        if self.we not in (None, Direction.WEST, Direction.EAST):
            raise ValueError(f"{self.we} is not a west-east direction")

    @property
    def moving(self) -> bool:
        return self.ns is not None or self.we is not None


STOPPED = Motion()

_AXES: dict[str, tuple[str, dict[Direction, str]]] = {
    "ns": (
        "TELESCOPE_MOTION_NS",
        {Direction.NORTH: "MOTION_NORTH", Direction.SOUTH: "MOTION_SOUTH"},
    ),
    "we": ("TELESCOPE_MOTION_WE", {Direction.WEST: "MOTION_WEST", Direction.EAST: "MOTION_EAST"}),
}


class Mount(Device):
    INTERFACE = DeviceInterface.TELESCOPE
    REQUIRED = ("EQUATORIAL_EOD_COORD", "ON_COORD_SET")

    @property
    def coordinates(self) -> Coordinates:
        prop = self.prop("EQUATORIAL_EOD_COORD")
        return Coordinates(prop.number("RA"), prop.number("DEC"))

    @property
    def horizontal(self) -> Horizontal | None:
        """Only some drivers report it (not the ZWO mounts, nor the simulator)."""
        if not self.has("HORIZONTAL_COORD"):
            return None
        prop = self.prop("HORIZONTAL_COORD")
        return Horizontal(prop.number("ALT"), prop.number("AZ"))

    @property
    def slewing(self) -> bool:
        return self.prop("EQUATORIAL_EOD_COORD").state is PropertyState.BUSY

    @property
    def tracking(self) -> bool:
        return self.has("TELESCOPE_TRACK_STATE") and self.prop("TELESCOPE_TRACK_STATE").switch(
            "TRACK_ON"
        )

    @property
    def track_modes(self) -> list[str]:
        """Tracking rates the driver offers, as ``sidereal``, ``lunar``…"""
        if not self.has("TELESCOPE_TRACK_MODE"):
            return []
        return [_track_mode(name) for name in self.prop("TELESCOPE_TRACK_MODE").elements]

    @property
    def track_mode(self) -> str | None:
        if not self.has("TELESCOPE_TRACK_MODE"):
            return None
        on = _on(self.prop("TELESCOPE_TRACK_MODE"))
        return _track_mode(on) if on is not None else None

    @property
    def parked(self) -> bool:
        return self.has("TELESCOPE_PARK") and self.prop("TELESCOPE_PARK").switch("PARK")

    @property
    def parking(self) -> bool:
        """Parking or unparking right now."""
        return self.has("TELESCOPE_PARK") and self.prop("TELESCOPE_PARK").state is (
            PropertyState.BUSY
        )

    @property
    def can_park(self) -> bool:
        return self.has("TELESCOPE_PARK")

    @property
    def can_home(self) -> bool:
        return self.has("TELESCOPE_HOME") and "GO" in self.prop("TELESCOPE_HOME").elements

    @property
    def homing(self) -> bool:
        return self.has("TELESCOPE_HOME") and self.prop("TELESCOPE_HOME").state is (
            PropertyState.BUSY
        )

    @property
    def pier_side(self) -> PierSide:
        if not self.has("TELESCOPE_PIER_SIDE"):
            return PierSide.UNKNOWN
        prop = self.prop("TELESCOPE_PIER_SIDE")
        if prop.switch("PIER_EAST"):
            return PierSide.EAST
        if prop.switch("PIER_WEST"):
            return PierSide.WEST
        return PierSide.UNKNOWN

    @property
    def motion(self) -> Motion:
        """Manual motion the driver reports, axis by axis."""
        found: dict[str, Direction | None] = {}
        for axis, (name, elements) in _AXES.items():
            found[axis] = None
            if self.has(name):
                prop = self.prop(name)
                for direction, element in elements.items():
                    if element in prop.elements and prop.switch(element):
                        found[axis] = direction
        return Motion(found["ns"], found["we"])

    @property
    def slew_rates(self) -> list[str]:
        """Manual motion speeds, slowest first, as the driver names them (``1x``…)."""
        if not self.has("TELESCOPE_SLEW_RATE"):
            return []
        return list(self.prop("TELESCOPE_SLEW_RATE").elements)

    @property
    def slew_rate(self) -> str | None:
        if not self.has("TELESCOPE_SLEW_RATE"):
            return None
        return _on(self.prop("TELESCOPE_SLEW_RATE"))

    @property
    def time(self) -> datetime | None:
        """The mount's clock, as it last reported it."""
        if not self.has("TIME_UTC"):
            return None
        try:
            parsed = datetime.fromisoformat(self.prop("TIME_UTC").text("UTC"))
        except (ValueError, KeyError):
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    @property
    def location(self) -> Location | None:
        if not self.has("GEOGRAPHIC_COORD"):
            return None
        prop = self.prop("GEOGRAPHIC_COORD")
        longitude = prop.number("LONG")
        return Location(
            prop.number("LAT"),
            longitude - 360 if longitude > 180 else longitude,
            prop.number("ELEV") if "ELEV" in prop.elements else 0.0,
        )

    @property
    def altitude_limits(self) -> AltitudeLimits | None:
        """Altitude limits the mount enforces itself (ZWO AM5 and AM7)."""
        names = ("ALTITUDE_LIMIT_CONTROL", "ALTITUDE_LOWER_LIMIT", "ALTITUDE_UPPER_LIMIT")
        if not all(self.has(name) for name in names):
            return None
        return AltitudeLimits(
            self.prop("ALTITUDE_LIMIT_CONTROL").switch("ENABLE"),
            self.prop("ALTITUDE_LOWER_LIMIT").number("LOWER_LIMIT"),
            self.prop("ALTITUDE_UPPER_LIMIT").number("UPPER_LIMIT"),
        )

    @property
    def meridian_limits(self) -> MeridianLimits | None:
        """Meridian flip settings (ZWO AM5 and AM7)."""
        if not (self.has("MERIDIAN_FLIP") and self.has("MERIDIAN_LIMIT")):
            return None
        return MeridianLimits(
            self.prop("MERIDIAN_FLIP").switch("INDI_ENABLED"),
            self.prop("MERIDIAN_LIMIT").number("LIMIT"),
        )

    # -- commands -----------------------------------------------------------

    async def goto(
        self, ra: float, dec: float, *, track: bool = True, timeout: float = SLEW_TIMEOUT
    ) -> None:
        """Slew to JNow coordinates; keep tracking there unless ``track`` is false."""
        await self._move_to(ra, dec, "TRACK" if track else "SLEW", timeout)

    async def sync(self, ra: float, dec: float, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Tell the mount it is pointing at these coordinates (e.g. after plate solving)."""
        await self._move_to(ra, dec, "SYNC", timeout)

    async def set_tracking(self, on: bool, timeout: float = DEFAULT_TIMEOUT) -> None:
        await self.command(
            "TELESCOPE_TRACK_STATE",
            {"TRACK_ON": on, "TRACK_OFF": not on},
            timeout=timeout,
            done=lambda p: p.switch("TRACK_ON") == on,
            # By convention the state is Busy while tracking and Idle when stopped.
            accept=frozenset({PropertyState.OK, PropertyState.BUSY, PropertyState.IDLE}),
        )

    async def set_track_mode(self, mode: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        elements = {_track_mode(name): name for name in self.prop("TELESCOPE_TRACK_MODE").elements}
        if mode not in elements:
            raise ValueError(f"{self.name} has no {mode} tracking; it has {', '.join(elements)}")
        await self.command(
            "TELESCOPE_TRACK_MODE",
            {name: name == elements[mode] for name in elements.values()},
            timeout=timeout,
            done=lambda p: p.switch(elements[mode]),
            accept=frozenset({PropertyState.OK, PropertyState.IDLE}),
        )

    async def park(self, timeout: float = SLEW_TIMEOUT) -> None:
        await self.command(
            "TELESCOPE_PARK",
            {"PARK": True, "UNPARK": False},
            timeout=timeout,
            done=lambda p: p.switch("PARK"),
        )

    async def unpark(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not self.parked:
            return
        await self.command(
            "TELESCOPE_PARK",
            {"PARK": False, "UNPARK": True},
            timeout=timeout,
            done=lambda p: p.switch("UNPARK"),
        )

    async def home(self, timeout: float = SLEW_TIMEOUT) -> None:
        """Go to the mount's home position (on ZWO mounts: pointing at the pole)."""
        if not self.can_home:
            raise DeviceError(f"{self.name} cannot go home")
        if self.parked:
            raise ValueError(f"{self.name} is parked")
        await self.command("TELESCOPE_HOME", {"GO": True}, timeout=timeout)

    async def abort(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        await self.command("TELESCOPE_ABORT_MOTION", {"ABORT": True}, timeout=timeout)

    async def set_slew_rate(self, rate: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        rates = self.slew_rates
        if rate not in rates:
            raise ValueError(f"{self.name} has no slew rate {rate}; it has {', '.join(rates)}")
        if self.slew_rate == rate:
            return
        await self.command(
            "TELESCOPE_SLEW_RATE",
            {name: name == rate for name in rates},
            timeout=timeout,
            done=lambda p: p.switch(rate),
            accept=frozenset({PropertyState.OK, PropertyState.IDLE}),
        )

    async def move(self, target: Motion, timeout: float = MOTION_TIMEOUT) -> None:
        """Start, change or stop manual motion, axis by axis, until told otherwise.

        Only axes whose direction changes are sent: drivers ignore a repeated
        start without answering. Reversing an axis stops it first, because INDI
        drivers treat a change of direction as a stop.
        """
        current = self.motion
        for axis in ("ns", "we"):
            now: Direction | None = getattr(current, axis)
            wanted: Direction | None = getattr(target, axis)
            if now == wanted:
                continue
            if now is not None:
                await self._axis(axis, None, timeout)
            if wanted is not None:
                if self.parked:
                    raise ValueError(f"{self.name} is parked")
                await self._axis(axis, wanted, timeout)

    async def stop(self, timeout: float = MOTION_TIMEOUT) -> None:
        """Stop manual motion on both axes, whatever this client believes is moving."""
        for axis in ("ns", "we"):
            name, _ = _AXES[axis]
            if self.has(name):
                await self._axis(axis, None, timeout)

    async def set_time(
        self, utc: datetime, offset_hours: float = 0.0, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        """Set the mount's clock; ``offset_hours`` is the local time zone (for its display)."""
        text = utc.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
        await self.command(
            "TIME_UTC", {"UTC": text, "OFFSET": f"{offset_hours:.2f}"}, timeout=timeout
        )

    async def set_location(self, location: Location, timeout: float = DEFAULT_TIMEOUT) -> None:
        if not -90 <= location.latitude <= 90 or not -180 <= location.longitude <= 180:
            raise ValueError(f"location out of range: {location}")
        values: dict[str, str | float | bool] = {
            "LAT": location.latitude,
            # INDI longitudes run east from 0 to 360.
            "LONG": location.longitude % 360,
        }
        if "ELEV" in self.prop("GEOGRAPHIC_COORD").elements:
            values["ELEV"] = location.elevation
        await self.command("GEOGRAPHIC_COORD", values, timeout=timeout)

    async def _axis(self, axis: str, direction: Direction | None, timeout: float) -> None:
        name, elements = _AXES[axis]
        values: dict[str, str | float | bool] = {
            element: d == direction for d, element in elements.items()
        }
        # Drivers answer a start with Busy, a stop with Idle, and a start they refuse
        # (parked, limits) with Idle or Alert.
        prop = await self.command(
            name,
            values,
            timeout=timeout,
            accept=frozenset({PropertyState.OK, PropertyState.BUSY, PropertyState.IDLE}),
        )
        if direction is None:
            if _on(prop) is not None:
                raise DeviceError(f"{self.name} did not stop moving {axis.upper()}")
        elif not prop.switch(elements[direction]) or prop.state is not PropertyState.BUSY:
            detail = f": {prop.message}" if prop.message else ""
            raise DeviceError(f"{self.name} refused to move {direction}{detail}")

    async def _move_to(self, ra: float, dec: float, mode: str, timeout: float) -> None:
        if not 0 <= ra < 24 or not -90 <= dec <= 90:
            raise ValueError(f"coordinates out of range: RA {ra} h, Dec {dec}°")
        if self.parked:
            raise ValueError(f"{self.name} is parked")
        # Drivers do not reliably acknowledge ON_COORD_SET; the coordinate update is
        # what tells us the action completed.
        modes = {m: m == mode for m in self.prop("ON_COORD_SET").elements}
        await self.client.send(self.name, "ON_COORD_SET", modes)
        await self.command("EQUATORIAL_EOD_COORD", {"RA": ra, "DEC": dec}, timeout=timeout)


def _on(prop: Property) -> str | None:
    """The first switch that is on."""
    return next((name for name in prop.elements if prop.switch(name)), None)


def _track_mode(element: str) -> str:
    return element.removeprefix("TRACK_").lower()
