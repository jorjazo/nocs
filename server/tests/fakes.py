"""Test doubles shared by the unit tests."""

from collections.abc import Callable, Mapping

from nocs.devices import DeviceInterface
from nocs.indi import IndiClient, Property, PropertyState, PropertyType, PropertyUpdated
from nocs.indi.properties import BlobElement, NumberElement, SwitchElement, TextElement
from nocs.indi.protocol import DefineProperty, DeleteProperty, ElementValue, Message, SetProperty

type Responder = Callable[[str, str, Mapping[str, str | float | bool]], object]


class FakeClient(IndiClient):
    """An IndiClient whose 'server' is the test: commands go to ``responder``."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[tuple[str, str, dict[str, str | float | bool]]] = []
        self.responder: Responder = lambda device, name, values: None

    async def send(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        self.sent.append((device, name, dict(values)))
        self.responder(device, name, values)

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
