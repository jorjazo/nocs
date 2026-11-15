"""Finding serial devices' ports by trying them (ADR 0048), against fake serial drivers."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from fakes import FakeClient, driver_info, number_property, switch_property, text_property

from nocs.devices import DeviceError, DeviceInterface
from nocs.devices import base as devices_base
from nocs.equipment import (
    DeviceConfig,
    EquipmentService,
    PortNotFoundError,
    Profile,
    ProfileStore,
    Role,
    SerialPort,
)
from nocs.equipment import detect as detect_module
from nocs.equipment import service as service_module
from nocs.equipment.ports import ranked, stable_name, words
from nocs.indi import IndiClient, PropertyState
from nocs.indi.drivers import DriverFifo
from nocs.state import Json, StateStore

BY_ID = "/dev/serial/by-id"
ZWO = SerialPort(f"{BY_ID}/usb-ZWO_Systems_ZWO_Device_123456-if00", "/dev/ttyACM0")
PEGASUS = SerialPort(
    f"{BY_ID}/usb-Pegasus_Astro_PPBADV_Gen2A_PPBA6MC1EN-if00-port0", "/dev/ttyUSB0"
)
CH340 = SerialPort(f"{BY_ID}/usb-1a86_USB_Serial-if00-port0", "/dev/ttyUSB1")
GPS = SerialPort(
    f"{BY_ID}/usb-u-blox_AG_-_www.u-blox.com_u-blox_7_-_GPS_GNSS_Receiver-if00", "/dev/ttyACM1"
)
SEARCH_OFF = {"INDI_ENABLED": False, "INDI_DISABLED": True}

MOUNT_DRIVER = "indi_lx200am5"
POWER_DRIVER = "indi_pegasus_ppba"
FOCUSER_DRIVER = "indi_fake_focus"


@dataclass
class SerialDevice:
    name: str
    interfaces: DeviceInterface
    port: SerialPort | None
    """Where it is plugged in; None: unplugged."""
    wrong_port: str = "alert"
    """What its driver does on another device's port: "alert", or "hang" (the AM5's)."""
    serial: bool = True
    saved_port: str = "/dev/ttyUSB0"
    """The port its driver starts with: both real drivers' factory default."""
    network: bool = False
    """Connected over the network: it defines a serial port all the same (the AM5's)."""
    baud: bool = True
    """Whether it defines DEVICE_BAUD_RATE: INDI's serial connection does."""
    refusals: int = 0
    """Times it refuses on its own port first: the PPBA, still answering the AM5's
    handshake when its own driver asks."""
    hung: bool = field(default=False, init=False)


class Server:
    """A fake indiserver whose serial drivers connect only on their device's port."""

    def __init__(self, devices: Mapping[str, SerialDevice]) -> None:
        self.devices = dict(devices)
        self.client = FakeClient()
        self.client.responder = self.respond
        self.connects: list[tuple[str, str]] = []
        """(device, port) of every connection attempt of a serial device."""

    def run(self, driver: str) -> None:
        device = self.devices[driver]
        client = self.client
        client.define(driver_info(device.name, device.interfaces, driver))
        client.define(switch_property(device.name, "CONNECTION", CONNECT=False, DISCONNECT=True))
        if device.serial or device.network:
            client.define(text_property(device.name, "DEVICE_PORT", PORT=device.saved_port))
            if device.baud:
                rates = switch_property(device.name, "DEVICE_BAUD_RATE", **{"9600": True})
                client.define(rates)
            search = switch_property(
                device.name, "DEVICE_AUTO_SEARCH", INDI_ENABLED=True, INDI_DISABLED=False
            )
            client.define(search)
        if device.network:
            mode = switch_property(
                device.name, "CONNECTION_MODE", CONNECTION_SERIAL=False, CONNECTION_TCP=True
            )
            client.define(mode)

    def stop(self, driver: str) -> None:
        device = self.devices[driver]
        device.hung = False
        self.client.answering = True
        self.client.delete(device.name)

    def device(self, name: str) -> SerialDevice:
        return next(d for d in self.devices.values() if d.name == name)

    def respond(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        client = self.client
        target = self.device(device)
        if target.hung:
            return
        if name == "DEVICE_PORT":
            port = {"PORT": str(values["PORT"])}
            loop.call_soon(client.update, device, name, PropertyState.OK, port)
        elif name == "DEVICE_AUTO_SEARCH":
            on = values.get("INDI_ENABLED") is True
            switches = {"INDI_ENABLED": on_off(on), "INDI_DISABLED": on_off(not on)}
            loop.call_soon(client.update, device, name, PropertyState.OK, switches)
        elif name == "CONNECTION":
            self.connection(target, values.get("CONNECT") is True)

    def connection(self, target: SerialDevice, on: bool) -> None:
        loop = asyncio.get_running_loop()
        client, device = self.client, target.name
        off = {"CONNECT": "Off", "DISCONNECT": "On"}
        if not on:
            loop.call_soon(client.update, device, "CONNECTION", PropertyState.IDLE, off)
            return
        chosen = ""
        if target.serial and not target.network:
            port = client.get_property(device, "DEVICE_PORT")
            chosen = port.text("PORT") if port is not None else ""
            self.connects.append((device, chosen))
        plugged = target.port
        own = plugged is not None and chosen in (plugged.path, plugged.device)
        right = own or not target.serial or target.network
        if right and target.refusals > 0:
            target.refusals -= 1
            right = False
        if right:
            connected = {"CONNECT": "On", "DISCONNECT": "Off"}
            loop.call_soon(client.update, device, "CONNECTION", PropertyState.OK, connected)
            if target.interfaces & DeviceInterface.TELESCOPE:
                loop.call_soon(client.define, number_property(device, "EQUATORIAL_EOD_COORD"))
                loop.call_soon(client.define, switch_property(device, "ON_COORD_SET"))
            if target.interfaces & DeviceInterface.POWER:
                loop.call_soon(client.define, number_property(device, "WEATHER_PARAMETERS"))
                loop.call_soon(client.define, switch_property(device, "POWER_CHANNELS"))
            if target.interfaces & DeviceInterface.FOCUSER:
                loop.call_soon(client.define, number_property(device, "ABS_FOCUS_POSITION"))
        elif target.wrong_port == "hang" and not own:
            target.hung = True
            client.answering = False
        else:
            failed = f"Handshake failed on {chosen}"
            loop.call_soon(client.update, device, "CONNECTION", PropertyState.ALERT, off, failed)


def on_off(on: bool) -> str:
    return "On" if on else "Off"


class FakeBridge:
    def __init__(self, client: IndiClient) -> None:
        self.client: IndiClient | None = client

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        return lambda: None


class FakeFifo(DriverFifo):
    def __init__(self, server: Server) -> None:
        super().__init__(Path("/nonexistent"))
        self.server = server
        self.commands: list[tuple[str, str]] = []

    def start(self, driver: str) -> None:
        self.commands.append(("start", driver))
        asyncio.get_running_loop().call_soon(self.server.run, driver)

    def stop(self, driver: str) -> None:
        self.commands.append(("stop", driver))
        asyncio.get_running_loop().call_soon(self.server.stop, driver)


def mount(port: SerialPort | None = ZWO, wrong_port: str = "hang") -> SerialDevice:
    return SerialDevice("ZWO AM5", DeviceInterface.TELESCOPE, port, wrong_port)


def power(port: SerialPort | None = PEGASUS) -> SerialDevice:
    return SerialDevice("Pegasus PPBA", DeviceInterface.POWER | DeviceInterface.WEATHER, port)


def rig_profile(*, mount: str | None = None, power: str | None = None) -> Profile:
    """The lab's rig: AM5, PPBA (power and weather) and a USB focuser, with these ports."""
    return Profile(
        name="Lab",
        devices={
            Role.MOUNT: DeviceConfig(driver=MOUNT_DRIVER, model="ZWO AM5 USB", port=mount),
            Role.POWER: DeviceConfig(driver=POWER_DRIVER, model="Pegasus PPBA", port=power),
            Role.WEATHER: DeviceConfig(driver=POWER_DRIVER, model="Pegasus PPBA", port=power),
            Role.FOCUSER: DeviceConfig(driver=FOCUSER_DRIVER),
        },
    )


def mount_only() -> Profile:
    return Profile(name="Lab", devices={Role.MOUNT: DeviceConfig(driver=MOUNT_DRIVER)})


@pytest.fixture(autouse=True)
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "SETTLE_QUIET", 0.01)
    monkeypatch.setattr(detect_module, "CONNECT_TIMEOUT", 0.2)
    monkeypatch.setattr(devices_base, "PROBE_TIMEOUT", 0.05)


@dataclass
class Rig:
    server: Server
    fifo: FakeFifo
    profiles: ProfileStore
    store: StateStore
    service: EquipmentService


type Factory = Callable[..., Rig]


@pytest.fixture
async def make_rig(tmp_path: Path) -> AsyncIterator[Factory]:
    made: list[EquipmentService] = []

    def make(
        *devices: SerialDevice,
        profile: Profile | None = None,
        ports: list[SerialPort] | None = None,
        reserved: tuple[str, ...] = (),
    ) -> Rig:
        drivers = {
            MOUNT_DRIVER: mount(),
            POWER_DRIVER: power(),
            FOCUSER_DRIVER: SerialDevice("ZWO EAF", DeviceInterface.FOCUSER, None, serial=False),
        }
        for device in devices:
            telescope = device.interfaces & DeviceInterface.TELESCOPE
            drivers[MOUNT_DRIVER if telescope else POWER_DRIVER] = device
        server = Server(drivers)
        fifo = FakeFifo(server)
        profiles = ProfileStore(tmp_path)
        profiles.put("lab", profile or rig_profile())
        store = StateStore()
        listed = [ZWO, PEGASUS, CH340, GPS] if ports is None else ports
        service = EquipmentService(
            store,
            profiles,
            FakeBridge(server.client),
            fifo,
            driver_timeout=1.0,
            ports=lambda: listed,
            reserved_ports=lambda: reserved,
        )
        made.append(service)
        return Rig(server, fifo, profiles, store, service)

    yield make
    for service in made:
        await service.close()


async def connect(rig: Rig) -> dict[str, dict[str, Json]]:
    rig.service.connect("lab")
    subscription = rig.store.subscribe()
    try:
        async with asyncio.timeout(10):
            while rig.store.get(("equipment", "connection")) != "connected":
                await subscription.get()
    finally:
        subscription.close()
    devices = rig.store.get(("equipment", "devices"))
    assert isinstance(devices, dict)
    return {role: cast(dict[str, Json], d) for role, d in devices.items()}


def statuses(roles: dict[str, dict[str, Json]]) -> dict[str, Json]:
    return {role: d["status"] for role, d in roles.items()}


def saved_ports(rig: Rig) -> dict[Role, str | None]:
    profile = rig.profiles.get("lab")
    assert profile is not None
    return {role: config.port for role, config in profile.devices.items()}


def tried(rig: Rig, device: str) -> list[str]:
    return [port for name, port in rig.server.connects if name == device]


# -- choosing the ports to try -------------------------------------------------------


def test_words_say_who_made_the_device() -> None:
    assert words("ZWO AM5", "ZWO AM5 USB", "indi_lx200am5") == {"zwo", "am5", "lx200am5"}
    assert words("Pegasus PPBA", None, "indi_pegasus_ppba") == {"pegasus", "ppba"}


def test_ports_matching_the_device_come_first() -> None:
    ports = [PEGASUS, CH340, ZWO, GPS]
    mount_words = words("ZWO AM5", "indi_lx200am5")
    power_words = words("Pegasus PPBA", "indi_pegasus_ppba")
    assert ranked(ports, mount_words, [power_words]) == [ZWO, CH340, PEGASUS]
    assert ranked(ports, power_words, [mount_words]) == [PEGASUS, CH340, ZWO]
    # Without the other devices' words, the rest keep the listing's order.
    assert ranked(ports, mount_words) == [ZWO, PEGASUS, CH340]


def test_taken_ports_and_gps_receivers_are_not_tried() -> None:
    ports = [ZWO, PEGASUS, CH340, GPS]
    assert ranked(ports, set(), exclude=[PEGASUS.path]) == [ZWO, CH340]
    # Taken by its device node (another device's DEVICE_PORT, gpsd's path).
    assert ranked(ports, set(), exclude=["/dev/ttyUSB1"]) == [ZWO, PEGASUS]


def test_stable_name_of_a_device_node() -> None:
    assert stable_name(PEGASUS.path, [ZWO, PEGASUS]) == PEGASUS.path
    assert stable_name("/dev/ttyAMA0", [ZWO, PEGASUS]) == "/dev/ttyAMA0"


# -- connecting a profile ------------------------------------------------------------


async def test_connecting_finds_the_ports_and_keeps_them(make_rig: Factory) -> None:
    rig = make_rig()
    roles = await connect(rig)
    assert statuses(roles) == {
        "mount": "ready",
        "power": "ready",
        "weather": "ready",
        "focuser": "ready",
    }
    assert saved_ports(rig) == {
        Role.MOUNT: ZWO.path,
        Role.POWER: PEGASUS.path,
        Role.WEATHER: PEGASUS.path,
        Role.FOCUSER: None,
    }
    # Each found at the first try (stable names that look like them), with the driver's
    # own search off: a driver that fails must not go on to the other devices' ports.
    assert tried(rig, "ZWO AM5") == [ZWO.path]
    assert tried(rig, "Pegasus PPBA") == [PEGASUS.path]
    for device in ("ZWO AM5", "Pegasus PPBA"):
        assert (device, "DEVICE_AUTO_SEARCH", SEARCH_OFF) in rig.server.client.sent
    assert rig.store.get(("equipment", "detecting")) is None
    assert rig.service.active_profile == rig.profiles.get("lab")


async def test_a_driver_that_hangs_on_a_wrong_port_is_restarted(make_rig: Factory) -> None:
    """The lab's AM5 on 2026-11-15: its driver opened the PPBA's port and never came back."""
    hidden = SerialPort(f"{BY_ID}/usb-1a86_USB_Serial-if00-port1", "/dev/ttyUSB2")
    # Plugged in through an adapter whose name says nothing, listed after a power box's.
    rig = make_rig(mount(port=hidden), profile=mount_only(), ports=[PEGASUS, hidden])
    roles = await connect(rig)
    assert roles["mount"]["status"] == "ready"
    assert tried(rig, "ZWO AM5") == [PEGASUS.path, hidden.path]
    assert rig.fifo.commands == [
        ("start", MOUNT_DRIVER),
        ("stop", MOUNT_DRIVER),
        ("start", MOUNT_DRIVER),
    ]
    assert saved_ports(rig) == {Role.MOUNT: hidden.path}


async def test_a_device_that_refuses_once_is_asked_again(make_rig: Factory) -> None:
    """On the lab, the PPBA's first handshake after the AM5's driver had tried its port
    failed at once (its driver read the answer to the AM5's), the second worked."""
    device = power()
    device.refusals = 1
    rig = make_rig(device)
    roles = await connect(rig)
    assert roles["power"]["status"] == "ready"
    assert tried(rig, "Pegasus PPBA") == [PEGASUS.path, PEGASUS.path]
    # The same with the port in the profile.
    device.refusals = 1
    profiled = make_rig(device, profile=rig_profile(mount=ZWO.path, power=PEGASUS.path))
    roles = await connect(profiled)
    assert roles["power"]["status"] == "ready"
    assert tried(profiled, "Pegasus PPBA") == [PEGASUS.path, PEGASUS.path]


async def test_ports_in_the_profile_are_used_as_they_are(make_rig: Factory) -> None:
    rig = make_rig(profile=rig_profile(mount=ZWO.path, power=PEGASUS.path))
    roles = await connect(rig)
    assert roles["mount"]["status"] == "ready"
    assert tried(rig, "ZWO AM5") == [ZWO.path]
    assert ("ZWO AM5", "DEVICE_AUTO_SEARCH", SEARCH_OFF) in rig.server.client.sent


async def test_a_wrong_port_in_the_profile_fails_without_looking(make_rig: Factory) -> None:
    """A port that is plugged in stays the profile's choice: the device may be off."""
    rig = make_rig(mount(wrong_port="alert"), profile=rig_profile(mount=CH340.path))
    roles = await connect(rig)
    assert roles["mount"]["status"] == "error"
    assert tried(rig, "ZWO AM5") == [CH340.path, CH340.path]  # refused, then once more
    assert saved_ports(rig)[Role.MOUNT] == CH340.path


async def test_a_port_no_longer_plugged_in_is_looked_for_again(make_rig: Factory) -> None:
    gone = f"{BY_ID}/usb-FTDI_FT232R_USB_UART_A10KQ2-if00-port0"
    rig = make_rig(power(port=CH340), profile=rig_profile(mount=ZWO.path, power=gone))
    roles = await connect(rig)
    assert roles["power"]["status"] == "ready"
    assert saved_ports(rig)[Role.POWER] == CH340.path
    assert saved_ports(rig)[Role.WEATHER] == CH340.path


async def test_ports_of_the_other_devices_and_gpsd_are_not_tried(make_rig: Factory) -> None:
    # The PPBA's port is the profile's and the CH340 adapter gpsd's: the mount, on none
    # of them, has only the ZWO port left to try.
    rig = make_rig(
        mount(port=None),
        profile=rig_profile(power=PEGASUS.path),
        reserved=("/dev/ttyUSB1",),
    )
    roles = await connect(rig)
    assert roles["mount"]["status"] == "error"
    assert "answered on none of 1 serial ports" in str(roles["mount"]["error"])
    assert tried(rig, "ZWO AM5") == [ZWO.path]


async def test_no_serial_ports_at_all(make_rig: Factory) -> None:
    rig = make_rig(ports=[])
    roles = await connect(rig)
    assert roles["mount"]["status"] == "error"
    assert "no serial port to look for ZWO AM5" in str(roles["mount"]["error"])
    assert roles["focuser"]["status"] == "ready"


async def test_a_port_the_driver_remembers_is_tried_last(make_rig: Factory) -> None:
    """A Pi's own UART is no USB adapter: only the driver's saved port names it."""
    uart = SerialPort("/dev/null", "/dev/null")  # a node that exists, outside by-id
    device = mount(port=uart, wrong_port="alert")
    device.saved_port = "/dev/null"
    rig = make_rig(device, profile=mount_only(), ports=[CH340])
    roles = await connect(rig)
    assert roles["mount"]["status"] == "ready"
    assert tried(rig, "ZWO AM5") == [CH340.path, CH340.path, "/dev/null"]
    assert saved_ports(rig) == {Role.MOUNT: "/dev/null"}


async def test_simulators_keep_their_port(make_rig: Factory) -> None:
    """The telescope simulator defines a serial port it never opens."""
    simulator = SerialDevice("Telescope Simulator", DeviceInterface.TELESCOPE, None)
    simulator.serial = False  # connects whatever its port
    rig = make_rig(
        simulator,
        profile=Profile(
            name="Lab", devices={Role.MOUNT: DeviceConfig(driver="indi_simulator_telescope")}
        ),
    )
    rig.server.devices = {"indi_simulator_telescope": simulator}
    original = rig.server.run

    def run(driver: str) -> None:
        original(driver)
        port = text_property(simulator.name, "DEVICE_PORT", PORT="/dev/ttyUSB0")
        rig.server.client.define(port)

    rig.server.run = run
    roles = await connect(rig)
    assert roles["mount"]["status"] == "ready"
    assert not [sent for sent in rig.server.client.sent if sent[1] == "DEVICE_PORT"]
    assert saved_ports(rig) == {Role.MOUNT: None}


async def test_edits_saved_during_a_search_are_kept(make_rig: Factory) -> None:
    hidden = SerialPort(f"{BY_ID}/usb-1a86_USB_Serial-if00-port1", "/dev/ttyUSB2")
    rig = make_rig(mount(port=hidden), profile=mount_only(), ports=[PEGASUS, hidden])
    rig.service.connect("lab")
    subscription = rig.store.subscribe()
    try:
        async with asyncio.timeout(5):
            while rig.store.get(("equipment", "detecting")) is None:
                await subscription.get()
    finally:
        subscription.close()
    rig.service.save_profile("lab", Profile(name="Renamed", devices=mount_only().devices))
    await connect(rig)
    saved = rig.profiles.get("lab")
    assert saved is not None
    assert (saved.name, saved.devices[Role.MOUNT].port) == ("Renamed", hidden.path)


async def test_a_mount_over_the_network_takes_no_port(make_rig: Factory) -> None:
    """The AM5 over Wi-Fi keeps its factory /dev/ttyUSB0 in DEVICE_PORT: the PPBA's."""
    network = mount(port=None)
    network.network = True
    rig = make_rig(network, profile=mount_only())
    roles = await connect(rig)
    assert roles["mount"]["status"] == "ready"
    assert tried(rig, "ZWO AM5") == []
    assert await rig.service.detect_port(POWER_DRIVER, Role.POWER) == PEGASUS.path


async def test_a_port_that_is_no_serial_connection(make_rig: Factory) -> None:
    """A driver may use DEVICE_PORT for something else, without INDI's serial
    connection (no baud rate): it is not looked for."""
    other = power(port=SerialPort("/dev/ttyUSB0", "/dev/ttyUSB0"))  # its driver's own
    other.baud = False
    rig = make_rig(other)
    roles = await connect(rig)
    assert roles["power"]["status"] == "ready"
    assert tried(rig, "Pegasus PPBA") == [other.saved_port]
    with pytest.raises(DeviceError, match="does not use a serial port"):
        await rig.service.detect_port(MOUNT_DRIVER, Role.MAIN_CAMERA)


# -- from the profile editor ---------------------------------------------------------


async def test_detecting_from_the_editor_leaves_things_as_they_were(make_rig: Factory) -> None:
    rig = make_rig()
    port = await rig.service.detect_port(POWER_DRIVER, Role.POWER)
    assert port == PEGASUS.path
    assert rig.fifo.commands == [("start", POWER_DRIVER), ("stop", POWER_DRIVER)]
    # Nothing saved: the profile is the editor's to save.
    assert saved_ports(rig)[Role.POWER] is None
    disconnect = {"CONNECT": False, "DISCONNECT": True}
    assert ("Pegasus PPBA", "CONNECTION", disconnect) in rig.server.client.sent


async def test_detecting_skips_the_ports_the_editor_excludes(make_rig: Factory) -> None:
    rig = make_rig(mount(port=CH340, wrong_port="alert"))
    port = await rig.service.detect_port(MOUNT_DRIVER, Role.MOUNT, exclude=[ZWO.path])
    assert port == CH340.path
    assert tried(rig, "ZWO AM5") == [PEGASUS.path, PEGASUS.path, CH340.path]


async def test_a_connected_device_says_its_port(make_rig: Factory) -> None:
    rig = make_rig()
    await connect(rig)
    attempts = len(rig.server.connects)
    assert await rig.service.detect_port(MOUNT_DRIVER, Role.MOUNT) == ZWO.path
    assert len(rig.server.connects) == attempts


async def test_detecting_a_device_that_is_not_serial(make_rig: Factory) -> None:
    rig = make_rig()
    with pytest.raises(DeviceError, match="does not use a serial port"):
        await rig.service.detect_port(FOCUSER_DRIVER, Role.FOCUSER)


async def test_detecting_a_device_found_nowhere(make_rig: Factory) -> None:
    rig = make_rig(power(port=None))
    with pytest.raises(PortNotFoundError, match="answered on none of 3 serial ports"):
        await rig.service.detect_port(POWER_DRIVER, Role.POWER)
    assert rig.store.get(("equipment", "detecting")) is None


async def test_progress_is_in_the_state(make_rig: Factory) -> None:
    rig = make_rig(power(port=CH340))
    seen: list[Json] = []
    subscription = rig.store.subscribe()

    async def watch() -> None:
        while True:
            await subscription.get()
            detecting = rig.store.get(("equipment", "detecting"))
            if detecting is not None and detecting not in seen:
                seen.append(detecting)

    task = asyncio.create_task(watch())
    try:
        assert await rig.service.detect_port(POWER_DRIVER, Role.POWER) == CH340.path
    finally:
        task.cancel()
        subscription.close()
    assert seen == [
        {"device": "Pegasus PPBA", "port": PEGASUS.path, "attempt": 1, "attempts": 3},
        {"device": "Pegasus PPBA", "port": ZWO.path, "attempt": 2, "attempts": 3},
        {"device": "Pegasus PPBA", "port": CH340.path, "attempt": 3, "attempts": 3},
    ]


async def test_listing_and_detecting_at_once_share_the_driver(make_rig: Factory) -> None:
    """The editor lists a driver's devices while Detect runs: the driver is started
    once, and stopped only after both."""
    rig = make_rig(power(port=CH340))
    listed, port = await asyncio.gather(
        rig.service.list_devices(POWER_DRIVER, Role.POWER),
        rig.service.detect_port(POWER_DRIVER, Role.POWER),
    )
    assert (listed, port) == (["Pegasus PPBA"], CH340.path)
    assert rig.fifo.commands == [("start", POWER_DRIVER), ("stop", POWER_DRIVER)]
