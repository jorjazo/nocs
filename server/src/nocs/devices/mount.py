from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from nocs.devices.base import DEFAULT_TIMEOUT, Device, DeviceInterface
from nocs.indi import PropertyState

SLEW_TIMEOUT = 300.0


@dataclass(frozen=True, slots=True)
class Coordinates:
    """Equatorial coordinates of the current epoch (JNow): RA in hours, Dec in degrees."""

    ra: float
    dec: float


class PierSide(StrEnum):
    EAST = "east"
    WEST = "west"
    UNKNOWN = "unknown"


class Mount(Device):
    INTERFACE = DeviceInterface.TELESCOPE
    REQUIRED = ("EQUATORIAL_EOD_COORD", "ON_COORD_SET")

    @property
    def coordinates(self) -> Coordinates:
        prop = self.prop("EQUATORIAL_EOD_COORD")
        return Coordinates(prop.number("RA"), prop.number("DEC"))

    @property
    def slewing(self) -> bool:
        return self.prop("EQUATORIAL_EOD_COORD").state is PropertyState.BUSY

    @property
    def tracking(self) -> bool:
        return self.has("TELESCOPE_TRACK_STATE") and self.prop("TELESCOPE_TRACK_STATE").switch(
            "TRACK_ON"
        )

    @property
    def parked(self) -> bool:
        return self.has("TELESCOPE_PARK") and self.prop("TELESCOPE_PARK").switch("PARK")

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

    async def goto(self, ra: float, dec: float, timeout: float = SLEW_TIMEOUT) -> None:
        """Slew to JNow coordinates and keep tracking there."""
        await self._move_to(ra, dec, "TRACK", timeout)

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

    async def abort(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        await self.command("TELESCOPE_ABORT_MOTION", {"ABORT": True}, timeout=timeout)

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
