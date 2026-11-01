"""Connecting equipment profiles, against a scripted fake server and driver FIFO."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path

import pytest
from fakes import FakeClient, driver_info, number_property, switch_property

from nocs.devices import DeviceInterface, DeviceUnresponsive, Focuser
from nocs.devices import base as devices_base
from nocs.equipment import (
    DeviceConfig,
    DriverRestartError,
    EquipmentBusyError,
    EquipmentService,
    Profile,
    ProfileStore,
    Role,
)
from nocs.equipment import service as service_module
from nocs.indi import IndiClient, PropertyState
from nocs.indi.drivers import DriverFifo
from nocs.state import Json, StateStore

FOCUSER_DRIVER = "indi_fake_focus"
POWER_DRIVER = "indi_fake_power"


class FakeBridge:
    def __init__(self) -> None:
        self.client: IndiClient | None = None
        self._watchers: list[Callable[[IndiClient | None], None]] = []

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        self._watchers.append(watcher)
        return lambda: self._watchers.remove(watcher)

    def attach(self, client: IndiClient | None) -> None:
        self.client = client
        for watcher in list(self._watchers):
            watcher(client)


class FakeFifo(DriverFifo):
    def __init__(
        self, on_start: Callable[[str], object], on_stop: Callable[[str], object] = lambda _: None
    ) -> None:
        super().__init__(Path("/nonexistent"))
        self.commands: list[tuple[str, str]] = []
        self.on_start = on_start
        self.on_stop = on_stop

    def start(self, driver: str) -> None:
        self.commands.append(("start", driver))
        self.on_start(driver)

    def stop(self, driver: str) -> None:
        self.commands.append(("stop", driver))
        self.on_stop(driver)


class Server:
    """A fake indiserver: devices that connect when asked, drivers that can be started."""

    DEVICES: Mapping[str, tuple[str, str, DeviceInterface]] = {
        FOCUSER_DRIVER: ("Focuser", FOCUSER_DRIVER, DeviceInterface.FOCUSER),
        POWER_DRIVER: ("Power", POWER_DRIVER, DeviceInterface.POWER | DeviceInterface.WEATHER),
    }

    def __init__(self) -> None:
        self.client = self.new_client()

    def new_client(self) -> FakeClient:
        client = FakeClient()
        client.responder = lambda device, name, values: self.respond(client, device, name, values)
        self.client = client
        return client

    def run(self, driver: str) -> None:
        name, executable, interfaces = self.DEVICES[driver]
        self.client.define(driver_info(name, interfaces, executable))
        self.client.define(switch_property(name, "CONNECTION", CONNECT=False, DISCONNECT=True))

    def respond(
        self, client: FakeClient, device: str, name: str, values: Mapping[str, str | float | bool]
    ) -> None:
        if name != "CONNECTION":
            return
        on = values.get("CONNECT") is True
        update = {"CONNECT": "On" if on else "Off", "DISCONNECT": "Off" if on else "On"}
        loop = asyncio.get_running_loop()
        # Like real drivers, a closed connection is reported Idle.
        state = PropertyState.OK if on else PropertyState.IDLE
        loop.call_soon(client.update, device, name, state, update)
        if on and device == "Focuser":
            # Like real drivers, the focuser defines its properties once connected.
            prop = number_property(device, "ABS_FOCUS_POSITION", FOCUS_ABSOLUTE_POSITION=10)
            loop.call_soon(client.define, prop)
        if on and device.startswith("Power"):
            loop.call_soon(client.define, number_property(device, "WEATHER_PARAMETERS"))
            loop.call_soon(client.define, switch_property(device, "POWER_CHANNELS"))


def profile(*, power_device: str | None = None) -> Profile:
    return Profile(
        name="Test rig",
        devices={
            Role.FOCUSER: DeviceConfig(driver=FOCUSER_DRIVER),
            Role.WEATHER: DeviceConfig(driver=POWER_DRIVER, device=power_device),
        },
    )


@pytest.fixture(autouse=True)
def fast_settle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_module, "SETTLE_QUIET", 0.01)


@pytest.fixture
def store() -> StateStore:
    return StateStore()


@pytest.fixture
def profiles(tmp_path: Path) -> ProfileStore:
    profiles = ProfileStore(tmp_path)
    profiles.put("rig", profile())
    return profiles


@pytest.fixture
def server() -> Server:
    return Server()


@pytest.fixture
def fifo(server: Server) -> FakeFifo:
    return FakeFifo(lambda driver: asyncio.get_running_loop().call_soon(server.run, driver))


@pytest.fixture
def bridge(server: Server) -> FakeBridge:
    bridge = FakeBridge()
    bridge.attach(server.client)
    return bridge


type Factory = Callable[..., EquipmentService]


@pytest.fixture
async def make_service(
    store: StateStore, profiles: ProfileStore, bridge: FakeBridge
) -> AsyncIterator[Factory]:
    services: list[EquipmentService] = []

    def make(fifo: DriverFifo | None, driver_timeout: float = 1.0) -> EquipmentService:
        service = EquipmentService(store, profiles, bridge, fifo, driver_timeout=driver_timeout)
        services.append(service)
        return service

    yield make
    for service in services:
        await service.close()


def equipment(store: StateStore, *path: str) -> Json:
    return store.get(("equipment", *path))


async def until(store: StateStore, condition: Callable[[], bool], timeout: float = 3.0) -> None:
    subscription = store.subscribe()
    try:
        async with asyncio.timeout(timeout):
            while not condition():
                await subscription.get()
    finally:
        subscription.close()


async def connected(store: StateStore) -> None:
    await until(store, lambda: equipment(store, "connection") == "connected")


def statuses(store: StateStore) -> dict[str, Json]:
    devices = equipment(store, "devices")
    assert isinstance(devices, dict)
    return {role: d["status"] for role, d in devices.items() if isinstance(d, dict)}


async def test_initial_state_lists_profiles(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    fifo: FakeFifo,
) -> None:
    make_service(fifo)
    assert equipment(store, "profiles") == {"rig": {"name": "Test rig"}}
    assert equipment(store, "connection") == "disconnected"
    assert equipment(store, "active") is None


async def test_adopts_running_drivers(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    assert statuses(store) == {"focuser": "ready", "weather": "ready"}
    assert equipment(store, "devices", "focuser", "device") == "Focuser"
    assert fifo.commands == []
    assert profiles.active == "rig"

    service.disconnect()
    await until(store, lambda: equipment(store, "connection") == "disconnected")
    assert statuses(store) == {"focuser": "disconnected", "weather": "disconnected"}
    connection = server.client.get_property("Focuser", "CONNECTION")
    assert connection is not None
    assert not connection.switch("CONNECT")
    assert fifo.commands == []  # NOCS did not start them, so it leaves them running


async def test_one_device_plays_power_and_weather(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    profiles.put(
        "box",
        Profile.model_validate({"name": "Box", "devices": {"power_box": {"driver": POWER_DRIVER}}}),
    )
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("box")
    await connected(store)
    assert statuses(store) == {"power": "ready", "weather": "ready"}
    assert service.ready_device(Role.POWER) == service.ready_device(Role.WEATHER) == "Power"
    connects = [s for s in server.client.sent if s[1] == "CONNECTION"]
    assert connects == [("Power", "CONNECTION", {"CONNECT": True, "DISCONNECT": False})]


async def test_starts_missing_drivers_and_stops_them_on_disconnect(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    server.run(FOCUSER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    assert statuses(store) == {"focuser": "ready", "weather": "ready"}
    assert fifo.commands == [("start", POWER_DRIVER)]

    service.disconnect()
    await until(store, lambda: equipment(store, "connection") == "disconnected")
    assert fifo.commands == [("start", POWER_DRIVER), ("stop", POWER_DRIVER)]


async def test_missing_driver_without_fifo_fails_only_its_role(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
) -> None:
    server.run(FOCUSER_DRIVER)
    service = make_service(None)
    service.connect("rig")
    await connected(store)
    assert statuses(store) == {"focuser": "ready", "weather": "error"}
    error = equipment(store, "devices", "weather", "error")
    assert isinstance(error, str)
    assert "no driver FIFO" in error


async def test_driver_that_defines_nothing_is_stopped(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
) -> None:
    server.run(FOCUSER_DRIVER)
    fifo = FakeFifo(lambda driver: None)  # e.g. not installed: indiserver keeps restarting it
    service = make_service(fifo, driver_timeout=0.1)
    service.connect("rig")
    await connected(store)
    assert statuses(store)["weather"] == "error"
    error = equipment(store, "devices", "weather", "error")
    assert isinstance(error, str)
    assert "defined no device" in error
    assert fifo.commands == [("start", POWER_DRIVER), ("stop", POWER_DRIVER)]


async def test_named_device_that_the_driver_does_not_define(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    profiles.put("rig", profile(power_device="Pegasus PPBA"))
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo, driver_timeout=0.1)
    service.connect("rig")
    await connected(store)
    error = equipment(store, "devices", "weather", "error")
    assert error == f"{POWER_DRIVER} does not define Pegasus PPBA; it defines ['Power']"


async def test_several_candidates_need_a_device_name(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    server.client.define(driver_info("Power 2", DeviceInterface.WEATHER, POWER_DRIVER))
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    error = equipment(store, "devices", "weather", "error")
    assert isinstance(error, str)
    assert "several devices" in error
    assert "Power 2" in error


async def test_busy_while_another_profile_is_connected(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    profiles.put("other", profile())
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    with pytest.raises(EquipmentBusyError):
        service.connect("other")
    with pytest.raises(EquipmentBusyError):
        service.delete_profile("rig")
    with pytest.raises(KeyError):
        service.connect("missing")
    service.connect("rig")  # the same profile again: retry, not an error


async def test_resumes_after_indiserver_reconnects(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)

    bridge.attach(None)
    assert equipment(store, "connection") == "connecting"
    assert equipment(store, "error") == "lost connection to indiserver"
    assert statuses(store) == {"focuser": "waiting", "weather": "waiting"}

    # indiserver restarted: drivers NOCS did not start come back by themselves.
    client = server.new_client()
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    bridge.attach(client)
    await connected(store)
    assert statuses(store) == {"focuser": "ready", "weather": "ready"}
    assert equipment(store, "error") is None


async def test_notices_devices_disconnected_or_gone(
    make_service: Factory,
    store: StateStore,
    profiles: ProfileStore,
    bridge: FakeBridge,
    server: Server,
    fifo: FakeFifo,
) -> None:
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)

    server.client.update(
        "Power", "CONNECTION", PropertyState.OK, {"CONNECT": "Off", "DISCONNECT": "On"}
    )
    assert statuses(store)["weather"] == "disconnected"
    server.client.delete("Focuser")
    assert statuses(store)["focuser"] == "error"
    assert equipment(store, "devices", "focuser", "error") == "Focuser disappeared"


async def test_restarts_a_roles_driver_and_connects_it_again(
    make_service: Factory, store: StateStore, server: Server
) -> None:
    loop = asyncio.get_running_loop()
    # indiserver kills a stopped driver and deletes its devices.
    fifo = FakeFifo(
        lambda driver: loop.call_soon(server.run, driver),
        lambda driver: loop.call_soon(server.client.delete, Server.DEVICES[driver][0]),
    )
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    seen: list[Json] = []
    service.add_listener(lambda: seen.append(equipment(store, "devices", "focuser", "status")))

    await service.restart_driver(Role.FOCUSER)

    assert fifo.commands == [("stop", FOCUSER_DRIVER), ("start", FOCUSER_DRIVER)]
    assert statuses(store) == {"focuser": "ready", "weather": "ready"}
    assert "error" not in seen  # its devices going away was expected
    # It was running before NOCS connected, so it keeps running after.
    service.disconnect()
    await until(store, lambda: equipment(store, "connection") == "disconnected")
    assert fifo.commands[2:] == []


async def test_a_device_that_stops_answering_is_unresponsive_until_restarted(
    make_service: Factory, store: StateStore, server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe unanswered marks the roles unresponsive; a restart makes them ready (ADR 0030)."""
    monkeypatch.setattr(devices_base, "SILENCE", 0.05)
    monkeypatch.setattr(devices_base, "PROBE_TIMEOUT", 0.05)
    loop = asyncio.get_running_loop()
    fifo = FakeFifo(
        lambda driver: loop.call_soon(server.run, driver),
        lambda driver: loop.call_soon(server.client.delete, Server.DEVICES[driver][0]),
    )
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)

    server.client.answering = False
    with pytest.raises(DeviceUnresponsive):
        await Focuser(server.client, "Focuser").move_to(20, timeout=10)
    assert statuses(store) == {"focuser": "unresponsive", "weather": "ready"}
    focuser = equipment(store, "devices", "focuser")
    assert isinstance(focuser, dict)
    assert focuser["error"] == "Focuser is not answering (silent for 0 s)"
    assert isinstance(focuser["unresponsive_since"], str)
    assert service.ready_device(Role.FOCUSER) is None

    server.client.answering = True
    await service.restart_driver(Role.FOCUSER)
    assert statuses(store) == {"focuser": "ready", "weather": "ready"}
    assert equipment(store, "devices", "focuser", "unresponsive_since") is None


async def test_an_unresponsive_device_that_answers_again_is_ready(
    make_service: Factory, store: StateStore, server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(devices_base, "SILENCE", 0.05)
    monkeypatch.setattr(devices_base, "PROBE_TIMEOUT", 0.05)
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(None)
    service.connect("rig")
    await connected(store)
    server.client.answering = False
    with pytest.raises(DeviceUnresponsive):
        await Focuser(server.client, "Focuser").move_to(20, timeout=10)
    assert statuses(store)["focuser"] == "unresponsive"
    # Its driver was only stopped for a while (SIGCONT): it talks again.
    server.client.update("Focuser", "ABS_FOCUS_POSITION", PropertyState.OK)
    assert statuses(store)["focuser"] == "ready"
    assert service.ready_device(Role.FOCUSER) == "Focuser"


async def test_a_driver_that_does_not_stop_is_reported(
    make_service: Factory, store: StateStore, server: Server, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "DRIVER_STOP_TIMEOUT", 0.05)
    fifo = FakeFifo(lambda driver: None)  # indiserver itself hung: nothing goes away
    server.run(FOCUSER_DRIVER)
    server.run(POWER_DRIVER)
    service = make_service(fifo)
    service.connect("rig")
    await connected(store)
    with pytest.raises(DriverRestartError, match="cannot restart"):
        await service.restart_driver(Role.FOCUSER)
    assert statuses(store)["focuser"] == "error"


async def test_restarting_needs_a_connected_profile(make_service: Factory, fifo: FakeFifo) -> None:
    service = make_service(fifo)
    with pytest.raises(DriverRestartError, match="not connected"):
        await service.restart_driver(Role.FOCUSER)
