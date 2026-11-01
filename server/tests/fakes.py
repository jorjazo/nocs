"""Test doubles shared by the unit tests."""

import asyncio
from collections.abc import Callable, Mapping
from pathlib import Path

from nocs.devices import DeviceInterface
from nocs.indi import (
    IndiClient,
    Property,
    PropertyDefined,
    PropertyState,
    PropertyType,
    PropertyUpdated,
)
from nocs.indi.properties import BlobElement, NumberElement, SwitchElement, TextElement
from nocs.indi.protocol import (
    DefineProperty,
    DeleteProperty,
    ElementValue,
    Message,
    SetProperty,
    StreamParser,
)

RECORDINGS = Path(__file__).resolve().parents[2] / "dev" / "recordings"

type Responder = Callable[[str, str, Mapping[str, str | float | bool]], object]


class FakeClient(IndiClient):
    """An IndiClient whose 'server' is the test: commands go to ``responder``."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str, dict[str, str | float | bool]]] = []
        self.responder: Responder = lambda device, name, values: None
        self.answering = True
        """Drivers answer a getProperties (a probe, ADR 0030); False: they hang."""

    async def get_properties(self, device: str | None = None, name: str | None = None) -> None:
        if not self.answering:
            return
        loop = asyncio.get_running_loop()
        for properties in list(self.devices.values()):
            for prop in list(properties.values()):
                if device in (None, prop.device) and name in (None, prop.name):
                    loop.call_soon(self.define, prop)
        if (
            device is not None
            and name == "CONNECTION"
            and device in self.devices
            and not self.get_property(device, name)
        ):
            # A device the test defined without CONNECTION answers a probe all the same.
            answer = PropertyDefined(Property(device, name, PropertyType.SWITCH))
            loop.call_soon(self._emit, answer)  # pyright: ignore[reportPrivateUsage]

    async def send(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        self.sent.append((device, name, dict(values)))
        self.responder(device, name, values)

    def replay(self, recording: str, device: str) -> None:
        """Feed what a real driver sent (``dev/recordings/``) for one device."""
        messages = StreamParser().feed((RECORDINGS / recording).read_bytes())
        for message in messages:
            match message:
                case DefineProperty(property=prop) if prop.device == device:
                    self._handle(message)  # pyright: ignore[reportPrivateUsage]
                case SetProperty() | DeleteProperty() | Message() if message.device == device:
                    self._handle(message)  # pyright: ignore[reportPrivateUsage]
                case _:
                    pass

    def define(self, prop: Property) -> None:
        self._handle(DefineProperty(prop))  # pyright: ignore[reportPrivateUsage]

    def update(
        self,
        device: str,
        name: str,
        state: PropertyState,
        values: Mapping[str, str] | None = None,
        message: str | None = None,
    ) -> None:
        prop = self.get_property(device, name)
        assert prop is not None
        update = SetProperty(
            device=device,
            name=name,
            type=prop.type,
            state=state,
            timeout=None,
            timestamp=None,
            message=message,
            values={k: ElementValue(v, {}) for k, v in (values or {}).items()},
        )
        self._handle(update)  # pyright: ignore[reportPrivateUsage]

    def deliver_blob(self, device: str, name: str, data: bytes, fmt: str = ".fits") -> None:
        """An image arriving in a BLOB property."""
        prop = self.get_property(device, name)
        assert prop is not None
        element = prop.elements[name]
        assert isinstance(element, BlobElement)
        element.format, element.size, element.data = fmt, len(data), data
        prop.state = PropertyState.OK
        self._emit(PropertyUpdated(prop, (name,)))  # pyright: ignore[reportPrivateUsage]

    def message(self, device: str, text: str) -> None:
        self._handle(Message(device, None, text))  # pyright: ignore[reportPrivateUsage]

    def delete(self, device: str, name: str | None = None) -> None:
        self._handle(DeleteProperty(device, name, None, None))  # pyright: ignore[reportPrivateUsage]


def number_property(device: str, name: str, **elements: float) -> Property:
    prop = Property(device, name, PropertyType.NUMBER, state=PropertyState.OK)
    for key, value in elements.items():
        prop.elements[key] = NumberElement(key, key, value, max=100000)
    return prop


def driver_info(device: str, interfaces: DeviceInterface, driver: str = "indi_fake") -> Property:
    prop = Property(device, "DRIVER_INFO", PropertyType.TEXT)
    prop.elements["DRIVER_INTERFACE"] = TextElement("DRIVER_INTERFACE", "", str(int(interfaces)))
    prop.elements["DRIVER_EXEC"] = TextElement("DRIVER_EXEC", "", driver)
    return prop


def switch_property(device: str, name: str, **elements: bool) -> Property:
    prop = Property(device, name, PropertyType.SWITCH, state=PropertyState.OK)
    for key, value in elements.items():
        prop.elements[key] = SwitchElement(key, key, value)
    return prop
