from __future__ import annotations

from nocs.devices.base import Device, DeviceInterface
from nocs.indi import PropertyState

MOVE_TIMEOUT = 120.0


class Focuser(Device):
    INTERFACE = DeviceInterface.FOCUSER
    REQUIRED = ("ABS_FOCUS_POSITION",)

    @property
    def position(self) -> int:
        return round(self.prop("ABS_FOCUS_POSITION").number("FOCUS_ABSOLUTE_POSITION"))

    @property
    def max_position(self) -> int | None:
        if not self.has("FOCUS_MAX"):
            return None
        return round(self.prop("FOCUS_MAX").number("FOCUS_MAX_VALUE"))

    @property
    def temperature(self) -> float | None:
        """Temperature probe reading in °C, if the focuser has one."""
        if not self.has("FOCUS_TEMPERATURE"):
            return None
        return self.prop("FOCUS_TEMPERATURE").number("TEMPERATURE")

    @property
    def moving(self) -> bool:
        return self.prop("ABS_FOCUS_POSITION").state is PropertyState.BUSY

    async def move_to(self, position: int, timeout: float = MOVE_TIMEOUT) -> None:
        limit = self.max_position
        if position < 0 or (limit is not None and position > limit):
            raise ValueError(f"position {position} outside 0..{limit}")
        await self.command(
            "ABS_FOCUS_POSITION",
            {"FOCUS_ABSOLUTE_POSITION": position},
            timeout=timeout,
            done=lambda p: round(p.number("FOCUS_ABSOLUTE_POSITION")) == position,
        )

    async def abort(self) -> None:
        if self.has("FOCUS_ABORT_MOTION"):
            await self.command("FOCUS_ABORT_MOTION", {"ABORT": True})
