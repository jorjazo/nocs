from __future__ import annotations

from nocs.devices.base import Device, DeviceInterface
from nocs.indi import NumberElement, PropertyState

MOVE_TIMEOUT = 120.0


class Focuser(Device):
    """A focuser with absolute positions (relative-only focusers are not supported)."""

    INTERFACE = DeviceInterface.FOCUSER
    REQUIRED = ("ABS_FOCUS_POSITION",)

    @property
    def position(self) -> int:
        return round(self.prop("ABS_FOCUS_POSITION").number("FOCUS_ABSOLUTE_POSITION"))

    @property
    def max_position(self) -> int | None:
        """The highest position the driver accepts.

        ``FOCUS_MAX`` alone cannot be trusted: the ZWO EAF reports 100000 there
        (above that property's own maximum of 60000) while it refuses positions
        beyond the 47814 steps its absolute position allows.
        """
        limits: list[float] = []
        element = self.prop("ABS_FOCUS_POSITION").elements.get("FOCUS_ABSOLUTE_POSITION")
        if isinstance(element, NumberElement) and element.max > element.min:
            limits.append(element.max)
        if self.has("FOCUS_MAX"):
            limits.append(self.prop("FOCUS_MAX").number("FOCUS_MAX_VALUE"))
        positive = [limit for limit in limits if limit > 0]
        return round(min(positive)) if positive else None

    @property
    def temperature(self) -> float | None:
        """Temperature probe reading in °C, if the focuser has one."""
        if not self.has("FOCUS_TEMPERATURE"):
            return None
        return self.prop("FOCUS_TEMPERATURE").number("TEMPERATURE")

    @property
    def moving(self) -> bool:
        return any(
            self.has(name) and self.prop(name).state is PropertyState.BUSY
            for name in ("ABS_FOCUS_POSITION", "REL_FOCUS_POSITION")
        )

    @property
    def can_abort(self) -> bool:
        return self.has("FOCUS_ABORT_MOTION")

    def check_position(self, position: int) -> None:
        limit = self.max_position
        if position < 0 or (limit is not None and position > limit):
            raise ValueError(f"position {position} outside 0..{limit}")

    async def move_to(self, position: int, timeout: float = MOVE_TIMEOUT) -> None:
        self.check_position(position)
        await self.command(
            "ABS_FOCUS_POSITION",
            {"FOCUS_ABSOLUTE_POSITION": position},
            timeout=timeout,
            done=lambda p: round(p.number("FOCUS_ABSOLUTE_POSITION")) == position,
        )

    async def move_by(self, steps: int, timeout: float = MOVE_TIMEOUT) -> None:
        """Move outward (positive) or inward (negative), as an absolute move."""
        await self.move_to(self.position + steps, timeout)

    async def abort(self) -> None:
        if self.can_abort:
            await self.command("FOCUS_ABORT_MOTION", {"ABORT": True})
