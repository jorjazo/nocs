from __future__ import annotations

from collections.abc import Sequence

from nocs.devices.base import Device, DeviceInterface
from nocs.indi import NumberElement, PropertyState

CHANGE_TIMEOUT = 60.0


class FilterWheel(Device):
    """A filter wheel, standalone or built into a camera (slots are 1-based)."""

    INTERFACE = DeviceInterface.FILTER
    REQUIRED = ("FILTER_SLOT",)

    @property
    def slot(self) -> int:
        return round(self.prop("FILTER_SLOT").number("FILTER_SLOT_VALUE"))

    @property
    def slots(self) -> int:
        """How many slots the wheel has."""
        if names := self.names:
            return len(names)
        element = self.prop("FILTER_SLOT").elements.get("FILTER_SLOT_VALUE")
        return round(element.max) if isinstance(element, NumberElement) else 0

    @property
    def names(self) -> list[str]:
        if not self.has("FILTER_NAME"):
            return []
        prop = self.prop("FILTER_NAME")
        return [prop.text(name) for name in prop.elements]

    @property
    def filter(self) -> str | None:
        names = self.names
        name = names[self.slot - 1].strip() if 0 < self.slot <= len(names) else ""
        return name or None

    @property
    def moving(self) -> bool:
        return self.prop("FILTER_SLOT").state is PropertyState.BUSY

    def slot_of(self, name: str) -> int:
        wanted = name.strip().casefold()
        for index, candidate in enumerate(self.names, start=1):
            if candidate.strip().casefold() == wanted:
                return index
        raise ValueError(f"{self.name} has no filter named {name!r} (has {self.names})")

    async def select(self, filter: int | str, timeout: float = CHANGE_TIMEOUT) -> None:
        """Move to a slot number or to the slot holding the named filter."""
        slot = self.slot_of(filter) if isinstance(filter, str) else filter
        count = self.slots
        if slot < 1 or (count and slot > count):
            raise ValueError(f"slot {slot} outside 1..{count}")
        await self.command(
            "FILTER_SLOT",
            {"FILTER_SLOT_VALUE": slot},
            timeout=timeout,
            done=lambda p: round(p.number("FILTER_SLOT_VALUE")) == slot,
        )

    async def set_names(self, names: Sequence[str]) -> None:
        """Name every slot, in order (the driver keeps them in its configuration)."""
        prop = self.prop("FILTER_NAME")
        elements = list(prop.elements)
        if len(names) != len(elements):
            raise ValueError(f"{self.name} has {len(elements)} slots, got {len(names)} names")
        values = dict(zip(elements, (name.strip() for name in names), strict=True))
        await self.command(
            "FILTER_NAME",
            values,
            done=lambda p: all(p.text(k) == v for k, v in values.items()),
            # Drivers leave the names Idle or set them Ok.
            accept=frozenset({PropertyState.OK, PropertyState.IDLE}),
        )
