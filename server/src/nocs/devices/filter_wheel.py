from __future__ import annotations

from nocs.devices.base import Device, DeviceInterface

CHANGE_TIMEOUT = 60.0


class FilterWheel(Device):
    """A filter wheel, standalone or built into a camera (slots are 1-based)."""

    INTERFACE = DeviceInterface.FILTER
    REQUIRED = ("FILTER_SLOT",)

    @property
    def slot(self) -> int:
        return round(self.prop("FILTER_SLOT").number("FILTER_SLOT_VALUE"))

    @property
    def names(self) -> list[str]:
        if not self.has("FILTER_NAME"):
            return []
        prop = self.prop("FILTER_NAME")
        return [prop.text(name) for name in prop.elements]

    @property
    def filter(self) -> str | None:
        names = self.names
        return names[self.slot - 1] if 0 < self.slot <= len(names) else None

    def slot_of(self, name: str) -> int:
        wanted = name.strip().casefold()
        for index, candidate in enumerate(self.names, start=1):
            if candidate.strip().casefold() == wanted:
                return index
        raise ValueError(f"{self.name} has no filter named {name!r} (has {self.names})")

    async def select(self, filter: int | str, timeout: float = CHANGE_TIMEOUT) -> None:
        """Move to a slot number or to the slot holding the named filter."""
        slot = self.slot_of(filter) if isinstance(filter, str) else filter
        count = len(self.names)
        if slot < 1 or (count and slot > count):
            raise ValueError(f"slot {slot} outside 1..{count}")
        await self.command(
            "FILTER_SLOT",
            {"FILTER_SLOT_VALUE": slot},
            timeout=timeout,
            done=lambda p: round(p.number("FILTER_SLOT_VALUE")) == slot,
        )
