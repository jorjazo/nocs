"""Command semantics of the typed device layer, against a scripted fake server."""

import asyncio
from collections.abc import Callable, Mapping

import pytest

from nocs.devices import (
    Camera,
    Device,
    DeviceError,
    DeviceInterface,
    FilterWheel,
    Focuser,
    device_interfaces,
)
from nocs.indi import IndiClient, Property, PropertyState, PropertyType
from nocs.indi.properties import NumberElement, SwitchElement, TextElement
from nocs.indi.protocol import DefineProperty, DeleteProperty, ElementValue, SetProperty

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

    def delete(self, device: str, name: str | None = None) -> None:
        self._handle(DeleteProperty(device, name, None, None))  # pyright: ignore[reportPrivateUsage]


def number_property(device: str, name: str, **elements: float) -> Property:
    prop = Property(device, name, PropertyType.NUMBER, state=PropertyState.OK)
    for key, value in elements.items():
        prop.elements[key] = NumberElement(key, key, value, max=100000)
    return prop


def driver_info(device: str, interfaces: DeviceInterface) -> Property:
    prop = Property(device, "DRIVER_INFO", PropertyType.TEXT)
    prop.elements["DRIVER_INTERFACE"] = TextElement("DRIVER_INTERFACE", "", str(int(interfaces)))
    return prop


@pytest.fixture
def client() -> FakeClient:
    client = FakeClient()
    client.define(driver_info("Focuser", DeviceInterface.FOCUSER))
    client.define(number_property("Focuser", "ABS_FOCUS_POSITION", FOCUS_ABSOLUTE_POSITION=100))
    client.define(number_property("Focuser", "FOCUS_MAX", FOCUS_MAX_VALUE=1000))
    client.define(driver_info("Wheel", DeviceInterface.FILTER))
    names = Property("Wheel", "FILTER_NAME", PropertyType.TEXT)
    for i, name in enumerate(["L", "R", "G", "B", "Ha"], start=1):
        names.elements[f"FILTER_SLOT_NAME_{i}"] = TextElement(f"FILTER_SLOT_NAME_{i}", "", name)
    client.define(names)
    client.define(number_property("Wheel", "FILTER_SLOT", FILTER_SLOT_VALUE=1))
    return client


def test_interfaces_and_discovery(client: FakeClient) -> None:
    assert device_interfaces(client, "Focuser") == DeviceInterface.FOCUSER
    assert device_interfaces(client, "Unknown") == DeviceInterface.GENERAL
    assert [d.name for d in Focuser.find_all(client)] == ["Focuser"]
    assert [d.name for d in FilterWheel.find_all(client)] == ["Wheel"]


async def test_command_waits_for_fresh_ok_matching_target(client: FakeClient) -> None:
    focuser = Focuser(client, "Focuser")

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        loop.call_soon(
            client.update, device, name, PropertyState.BUSY, {"FOCUS_ABSOLUTE_POSITION": "150"}
        )
        loop.call_later(
            0.01, client.update, device, name, PropertyState.OK, {"FOCUS_ABSOLUTE_POSITION": "200"}
        )

    client.responder = respond
    await focuser.move_to(200, timeout=1)
    assert focuser.position == 200
    assert client.sent == [("Focuser", "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": 200})]


async def test_command_ignores_ok_that_does_not_reach_target(client: FakeClient) -> None:
    focuser = Focuser(client, "Focuser")

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        # Some drivers acknowledge with Ok while still at the old position.
        asyncio.get_running_loop().call_soon(client.update, device, name, PropertyState.OK)

    client.responder = respond
    with pytest.raises(DeviceError, match="no response"):
        await focuser.move_to(200, timeout=0.05)


async def test_alert_fails_the_command_with_driver_message(client: FakeClient) -> None:
    focuser = Focuser(client, "Focuser")
    client.responder = lambda device, name, _: asyncio.get_running_loop().call_soon(
        client.update, device, name, PropertyState.ALERT, None, "motor stalled"
    )
    with pytest.raises(DeviceError, match="motor stalled"):
        await focuser.move_to(200, timeout=1)


async def test_property_removed_during_command(client: FakeClient) -> None:
    focuser = Focuser(client, "Focuser")
    client.responder = lambda device, name, values: asyncio.get_running_loop().call_soon(
        client.delete, device
    )
    with pytest.raises(DeviceError, match="removed"):
        await focuser.move_to(200, timeout=1)


async def test_missing_property_is_a_device_error(client: FakeClient) -> None:
    with pytest.raises(DeviceError, match="no property"):
        await Device(client, "Focuser").command("NOPE", {"X": 1})


async def test_focuser_rejects_out_of_range(client: FakeClient) -> None:
    with pytest.raises(ValueError, match="outside"):
        await Focuser(client, "Focuser").move_to(5000)
    assert client.sent == []


async def test_filter_wheel_select_by_name(client: FakeClient) -> None:
    wheel = FilterWheel(client, "Wheel")
    client.responder = lambda device, name, values: asyncio.get_running_loop().call_soon(
        client.update,
        device,
        name,
        PropertyState.OK,
        {"FILTER_SLOT_VALUE": str(values["FILTER_SLOT_VALUE"])},
    )
    assert wheel.names == ["L", "R", "G", "B", "Ha"]
    await wheel.select("ha", timeout=1)
    assert (wheel.slot, wheel.filter) == (5, "Ha")
    with pytest.raises(ValueError, match="no filter named"):
        await wheel.select("OIII")
    with pytest.raises(ValueError, match="outside"):
        await wheel.select(9)


def test_switch_helpers_type_check() -> None:
    prop = Property("d", "CONNECTION", PropertyType.SWITCH)
    prop.elements["CONNECT"] = SwitchElement("CONNECT", "", True)
    assert prop.switch("CONNECT")
    with pytest.raises(TypeError):
        prop.number("CONNECT")


async def test_camera_waits_for_sensor_size(client: FakeClient) -> None:
    for name in ("CCD_EXPOSURE", "CCD_FRAME_TYPE", "CCD1", "CONNECTION"):
        client.define(Property("Cam", name, PropertyType.SWITCH))
    client.define(number_property("Cam", "CCD_INFO", CCD_MAX_X=0))
    camera = Camera(client, "Cam")
    assert camera.not_ready() == ["sensor size (CCD_INFO)"]
    asyncio.get_running_loop().call_later(
        0.01, client.update, "Cam", "CCD_INFO", PropertyState.OK, {"CCD_MAX_X": "6248"}
    )
    await camera.wait_ready(timeout=1)
    assert camera.not_ready() == []


async def test_connect_unknown_device_fails_fast(client: FakeClient) -> None:
    with pytest.raises(DeviceError, match="not found"):
        await Focuser(client, "Nope").connect(timeout=0.05)
