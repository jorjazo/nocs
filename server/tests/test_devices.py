"""Command semantics of the typed device layer, against a scripted fake server."""

import asyncio
from collections.abc import Mapping

import pytest
from fakes import FakeClient, driver_info, number_property, switch_property

from nocs.devices import (
    Camera,
    Device,
    DeviceError,
    DeviceInterface,
    DeviceUnresponsive,
    FilterWheel,
    Focuser,
    device_interfaces,
    on_unresponsive,
)
from nocs.devices import base as devices_base
from nocs.indi import Property, PropertyState, PropertyType
from nocs.indi.properties import SwitchElement, TextElement


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


@pytest.fixture
def quick_probes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(devices_base, "SILENCE", 0.05)
    monkeypatch.setattr(devices_base, "PROBE_TIMEOUT", 0.05)


@pytest.mark.usefixtures("quick_probes")
async def test_a_silent_device_that_answers_its_probe_keeps_its_command(
    client: FakeClient,
) -> None:
    """A quiet device is not a hung one (ADR 0030)."""
    focuser = Focuser(client, "Focuser")
    client.responder = lambda device, name, _: asyncio.get_running_loop().call_later(
        0.3, client.update, device, name, PropertyState.OK, {"FOCUS_ABSOLUTE_POSITION": "200"}
    )
    await focuser.move_to(200, timeout=1)
    assert focuser.position == 200


@pytest.mark.usefixtures("quick_probes")
async def test_a_silent_device_that_does_not_answer_is_unresponsive(client: FakeClient) -> None:
    reported: list[tuple[str, str]] = []
    on_unresponsive(client, lambda device, reason: reported.append((device, reason)))
    client.answering = False
    focuser = Focuser(client, "Focuser")
    loop = asyncio.get_running_loop()
    start = loop.time()
    with pytest.raises(DeviceUnresponsive, match=r"Focuser is not answering \(silent for 0 s\)"):
        await focuser.move_to(200, timeout=10)
    assert loop.time() - start < 1  # long before the deadline
    assert reported == [("Focuser", "Focuser is not answering (silent for 0 s)")]


@pytest.mark.usefixtures("quick_probes")
async def test_a_missed_deadline_is_probed_too(client: FakeClient) -> None:
    def chatter(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        # Busy and talking, but it never gets there.
        loop = asyncio.get_running_loop()
        for i in range(10):
            loop.call_later(0.02 * i, client.update, device, name, PropertyState.BUSY)

    client.responder = chatter
    focuser = Focuser(client, "Focuser")
    with pytest.raises(DeviceError, match=r"no response within 0\.1 s") as answered:
        await focuser.move_to(200, timeout=0.1)
    assert not isinstance(answered.value, DeviceUnresponsive)
    client.answering = False
    with pytest.raises(DeviceUnresponsive, match=r"not answering \(.*no response within 0.1 s\)"):
        await focuser.move_to(200, timeout=0.1)


async def test_alert_takes_its_reason_from_the_drivers_messages(client: FakeClient) -> None:
    focuser = Focuser(client, "Focuser")

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        # As the ZWO mounts do: the reason comes as messages, then the property turns Alert.
        loop = asyncio.get_running_loop()
        loop.call_soon(client.message, "Other", "[ERROR] unrelated")
        loop.call_soon(client.message, device, "[ERROR] Error moving to 200")
        loop.call_soon(client.message, device, "[ERROR] Move failed (-1).")
        loop.call_soon(client.update, device, name, PropertyState.ALERT)

    client.responder = respond
    with pytest.raises(DeviceError, match=r"failed: Error moving to 200; Move failed \(-1\)\.$"):
        await focuser.move_to(200, timeout=1)


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


@pytest.mark.usefixtures("quick_probes")
async def test_a_slow_connection_is_not_probed(client: FakeClient) -> None:
    """Drivers connect on their main thread: silent, and deaf to probes, until done."""
    client.define(switch_property("Focuser", "CONNECTION", CONNECT=False, DISCONNECT=True))
    client.answering = False

    def respond(device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        connected = {"CONNECT": "On", "DISCONNECT": "Off"}
        asyncio.get_running_loop().call_later(
            0.3, client.update, device, name, PropertyState.OK, connected
        )

    client.responder = respond
    await Focuser(client, "Focuser").connect(timeout=1)


def test_nameless_properties_are_ignored(client: FakeClient) -> None:
    client.define(Property("", "", PropertyType.LIGHT))
    client.define(Property("Focuser", "", PropertyType.NUMBER))
    assert "" not in client.devices
    assert "" not in client.devices["Focuser"]
