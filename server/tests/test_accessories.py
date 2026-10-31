"""Focuser and filter wheel: facades, services and per-wheel filter names, against fakes."""

import asyncio
import json
from collections.abc import Callable, Coroutine, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from fakes import FakeClient, driver_info, number_property

from nocs.devices import DeviceInterface, FilterWheel, Focuser
from nocs.equipment import EquipmentService, Role
from nocs.filters.service import FilterWheelService
from nocs.filters.wheels import WheelConfig, WheelStore, check_names, wheel_key
from nocs.focus.focusers import FocuserConfig, FocuserStore
from nocs.focus.service import FocuserService
from nocs.indi import IndiClient, Property, PropertyState, PropertyType
from nocs.indi.properties import NumberElement, SwitchElement, TextElement
from nocs.jobs import JobManager, ResourceBusyError
from nocs.state import StateStore

FOCUSER = "ZWO EAF"
KEY = f"device:{FOCUSER}"
WHEEL = "ZWO EFW"
DRIVER_NAMES = ["Red", "Green", "Blue", "H_Alpha", "SII"]


def define_focuser(client: FakeClient) -> None:
    """As the lab EAF defines itself: FOCUS_MAX above what the position accepts."""
    client.define(driver_info(FOCUSER, DeviceInterface.FOCUSER))
    position = Property(FOCUSER, "ABS_FOCUS_POSITION", PropertyType.NUMBER, state=PropertyState.OK)
    position.elements["FOCUS_ABSOLUTE_POSITION"] = NumberElement(
        "FOCUS_ABSOLUTE_POSITION", "Steps", 6231, max=47814
    )
    client.define(position)
    client.define(number_property(FOCUSER, "FOCUS_MAX", FOCUS_MAX_VALUE=100000))
    client.define(number_property(FOCUSER, "FOCUS_TEMPERATURE", TEMPERATURE=16.4))
    abort = Property(FOCUSER, "FOCUS_ABORT_MOTION", PropertyType.SWITCH)
    abort.elements["ABORT"] = SwitchElement("ABORT", "Abort", False)
    client.define(abort)


def define_wheel(client: FakeClient, serial: str | None = "33AF6560C0000000") -> None:
    client.define(driver_info(WHEEL, DeviceInterface.FILTER))
    slot = Property(WHEEL, "FILTER_SLOT", PropertyType.NUMBER, state=PropertyState.OK)
    slot.elements["FILTER_SLOT_VALUE"] = NumberElement(
        "FILTER_SLOT_VALUE", "Filter", 1, min=1, max=len(DRIVER_NAMES)
    )
    client.define(slot)
    names = Property(WHEEL, "FILTER_NAME", PropertyType.TEXT)
    for i, name in enumerate(DRIVER_NAMES, start=1):
        names.elements[f"FILTER_SLOT_NAME_{i}"] = TextElement(f"FILTER_SLOT_NAME_{i}", "", name)
    client.define(names)
    if serial is not None:
        prop = Property(WHEEL, "Serial Number", PropertyType.TEXT)
        prop.elements["SN"] = TextElement("SN", "Serial Number", serial)
        client.define(prop)


class Driver:
    """Answers moves and names the way the ZWO drivers do; moves wait for ``release``."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.hold = False
        self.release = asyncio.Event()
        self.aborted = 0
        self.tasks: set[asyncio.Task[None]] = set()

    def __call__(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        loop = asyncio.get_running_loop()
        update = self.client.update
        text = {k: str(v) for k, v in values.items()}
        match name:
            case "ABS_FOCUS_POSITION":
                target = round(float(values["FOCUS_ABSOLUTE_POSITION"]))
                loop.call_soon(update, device, name, PropertyState.BUSY)
                self._spawn(self._arrive(device, name, {"FOCUS_ABSOLUTE_POSITION": target}))
            case "FILTER_SLOT":
                self._spawn(self._arrive(device, name, text))
            case "FOCUS_ABORT_MOTION":
                self.aborted += 1
                loop.call_soon(update, device, "ABS_FOCUS_POSITION", PropertyState.IDLE)
                loop.call_soon(update, device, name, PropertyState.OK, {"ABORT": "Off"})
            case "FILTER_NAME":
                loop.call_soon(update, device, name, PropertyState.OK, text)
            case _:
                pass

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _arrive(self, device: str, name: str, values: Mapping[str, object]) -> None:
        if self.hold:
            await self.release.wait()
        prop = self.client.get_property(device, name)
        assert prop is not None
        if prop.state is not PropertyState.IDLE or name != "ABS_FOCUS_POSITION":
            text = {k: str(v) for k, v in values.items()}
            self.client.update(device, name, PropertyState.OK, text)


class FakeBridge:
    def __init__(self, client: IndiClient) -> None:
        self.client: IndiClient | None = client

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        return lambda: None


class FakeEquipment:
    def __init__(self) -> None:
        self.ready: dict[Role, str] = {}
        self._listeners: list[Callable[[], None]] = []

    def ready_device(self, role: Role) -> str | None:
        return self.ready.get(role)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def set_ready(self, role: Role, device: str | None) -> None:
        if device is None:
            self.ready.pop(role, None)
        else:
            self.ready[role] = device
        for listener in list(self._listeners):
            listener()


@pytest.fixture
def client() -> FakeClient:
    client = FakeClient()
    define_focuser(client)
    define_wheel(client)
    return client


@pytest.fixture
def driver(client: FakeClient) -> Driver:
    driver = Driver(client)
    client.responder = driver
    return driver


async def wait_until(condition: Callable[[], bool], timeout: float = 2) -> None:
    """Poll a condition on the fake driver, which offers nothing to wait on."""
    async with asyncio.timeout(timeout):
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0.005)


# -- facades ----------------------------------------------------------------------


def test_focuser_limit_ignores_a_focus_max_above_what_the_driver_accepts(
    client: FakeClient,
) -> None:
    focuser = Focuser(client, FOCUSER)
    assert focuser.max_position == 47814
    assert focuser.temperature == pytest.approx(16.4)
    with pytest.raises(ValueError, match=r"outside 0\.\.47814"):
        focuser.check_position(50000)


async def test_focuser_moves_by_steps(client: FakeClient, driver: Driver) -> None:
    focuser = Focuser(client, FOCUSER)
    await focuser.move_by(-231, timeout=1)
    assert focuser.position == 6000
    assert client.sent[-1] == (FOCUSER, "ABS_FOCUS_POSITION", {"FOCUS_ABSOLUTE_POSITION": 6000})


def test_wheel_reads(client: FakeClient) -> None:
    wheel = FilterWheel(client, WHEEL)
    assert (wheel.slots, wheel.slot, wheel.filter) == (5, 1, "Red")
    assert wheel.serial_number == "33AF6560C0000000"
    assert not wheel.moving


async def test_wheel_names_must_cover_every_slot(client: FakeClient, driver: Driver) -> None:
    wheel = FilterWheel(client, WHEEL)
    with pytest.raises(ValueError, match="5 slots"):
        await wheel.set_names(["L", "R"])
    await wheel.set_names(["L", "R", "G", "B", ""])
    assert wheel.names == ["L", "R", "G", "B", ""]
    assert client.sent[-1][2]["FILTER_SLOT_NAME_5"] == ""


# -- wheel store ------------------------------------------------------------------


def test_wheel_names_are_checked() -> None:
    assert check_names([" L ", "", "", "Ha"]) == ["L", "", "", "Ha"]
    with pytest.raises(ValueError, match="two slots"):
        check_names(["Ha", "ha"])
    assert wheel_key("123", WHEEL) == "serial:123"
    assert wheel_key(None, "Filter Simulator") == "device:Filter Simulator"


def test_wheel_store_round_trip(tmp_path: Path) -> None:
    store = WheelStore(tmp_path)
    assert store.load() == {}
    store.put("serial:1", WheelConfig(label="2600MM", filters=["L", "R"], confirmed=True))
    store.put("serial:2", WheelConfig(filters=["Ha"]))
    assert WheelStore(tmp_path).get("serial:1") == WheelConfig(
        label="2600MM", filters=["L", "R"], confirmed=True
    )
    saved = json.loads((tmp_path / "filter-wheels.json").read_text())
    assert set(saved["wheels"]) == {"serial:1", "serial:2"}
    (tmp_path / "filter-wheels.json").write_text("{not json")
    assert store.load() == {}


# -- focuser service --------------------------------------------------------------


def focuser_service(
    client: FakeClient, settings: FocuserStore | None = None
) -> tuple[FocuserService, JobManager, StateStore]:
    store = StateStore()
    jobs = JobManager(store)
    equipment = FakeEquipment()
    service = FocuserService(
        store, jobs, cast(EquipmentService, equipment), FakeBridge(client), settings
    )
    assert store.get(("focuser",)) is None
    equipment.set_ready(Role.FOCUSER, FOCUSER)
    return service, jobs, store


async def test_backlash_is_kept_per_physical_focuser(
    client: FakeClient, driver: Driver, tmp_path: Path
) -> None:
    settings = FocuserStore(tmp_path)
    service, _, store = focuser_service(client, settings)
    assert service.backlash() == FocuserConfig()
    service.set_backlash(FocuserConfig(direction="inward", overshoot=250))
    assert store.get(("focuser", "backlash")) == {"direction": "inward", "overshoot": 250}
    assert settings.get(KEY) == FocuserConfig(direction="inward", overshoot=250)
    # A new service (nocsd restarted) reads it back.
    again, _, store = focuser_service(client, FocuserStore(tmp_path))
    assert again.backlash().overshoot == 250
    assert store.get(("focuser", "backlash", "direction")) == "inward"


async def test_focuser_state_and_moves(client: FakeClient, driver: Driver) -> None:
    service, jobs, store = focuser_service(client)
    assert store.get(("focuser",)) == {
        "device": FOCUSER,
        "position": 6231,
        "max_position": 47814,
        "moving": False,
        "target": None,
        "temperature": pytest.approx(16.4),
        "can_abort": True,
        "key": KEY,
        "backlash": {"direction": "outward", "overshoot": None},
    }
    job = service.move_to(7000)
    await jobs.wait(job)
    assert store.get(("jobs", job, "state")) == "succeeded"
    assert store.get(("jobs", job, "result")) == {"position": 7000}
    job = service.move_by(-500)
    await jobs.wait(job)
    assert store.get(("focuser", "position")) == 6500
    with pytest.raises(ValueError, match="outside"):
        service.move_by(-7000)
    with pytest.raises(ValueError, match="steps"):
        service.move_by(0)


async def test_focuser_move_locks_and_abort_stops_it(client: FakeClient, driver: Driver) -> None:
    service, jobs, store = focuser_service(client)
    driver.hold = True
    job = service.move_to(9000)
    await wait_until(lambda: store.get(("focuser", "moving")) is True)
    assert store.get(("focuser", "target")) == 9000
    with pytest.raises(ResourceBusyError):
        service.move_by(10)
    await service.abort()
    await jobs.wait(job)
    assert store.get(("jobs", job, "state")) == "cancelled"
    assert driver.aborted >= 1
    assert store.get(("focuser", "target")) is None
    assert store.get(("focuser", "moving")) is False


async def test_focuser_state_follows_the_role(client: FakeClient) -> None:
    store = StateStore()
    equipment = FakeEquipment()
    FocuserService(store, JobManager(store), cast(EquipmentService, equipment), FakeBridge(client))
    equipment.set_ready(Role.FOCUSER, FOCUSER)
    assert store.get(("focuser", "device")) == FOCUSER
    equipment.set_ready(Role.FOCUSER, None)
    assert store.get(("focuser",)) is None


# -- filter wheel service ---------------------------------------------------------


def wheel_service(
    client: FakeClient, config_dir: Path
) -> tuple[FilterWheelService, JobManager, StateStore, FakeEquipment]:
    store = StateStore()
    jobs = JobManager(store)
    equipment = FakeEquipment()
    service = FilterWheelService(
        store,
        jobs,
        cast(EquipmentService, equipment),
        FakeBridge(client),
        WheelStore(config_dir),
        serial_wait=0.05,
    )
    return service, jobs, store, equipment


async def test_a_new_wheel_keeps_its_drivers_names_until_confirmed(
    client: FakeClient, driver: Driver, tmp_path: Path
) -> None:
    service, jobs, store, equipment = wheel_service(client, tmp_path)
    equipment.set_ready(Role.FILTER_WHEEL, WHEEL)
    await wait_until(lambda: store.get(("filter_wheel", "key")) is not None)
    assert store.get(("filter_wheel",)) == {
        "device": WHEEL,
        "key": "serial:33AF6560C0000000",
        "label": "",
        "slot": 1,
        "filter": "Red",
        "names": DRIVER_NAMES,
        "slots": 5,
        "moving": False,
        "confirmed": False,
    }
    assert not any(name == "FILTER_NAME" for _, name, _ in client.sent)
    wanted = ["L", "R", "G", "B", "Ha"]
    await service.set_names(wanted, "2600MM")
    assert FilterWheel(client, WHEEL).names == wanted
    assert store.get(("filter_wheel", "confirmed")) is True
    assert store.get(("filter_wheel", "label")) == "2600MM"
    assert store.get(("filter_wheel", "names")) == wanted
    saved = WheelStore(tmp_path).get("serial:33AF6560C0000000")
    assert saved == WheelConfig(label="2600MM", filters=wanted, confirmed=True)

    job = service.select("ha")
    await jobs.wait(job)
    assert store.get(("jobs", job, "result")) == {"slot": 5, "filter": "Ha"}
    assert store.get(("filter_wheel", "filter")) == "Ha"


async def test_a_known_wheel_gets_its_names_back(
    client: FakeClient, driver: Driver, tmp_path: Path
) -> None:
    """Another wheel was on the same driver (and device name) before: its names must go."""
    names = ["L", "Ha", "OIII", "SII", ""]
    WheelStore(tmp_path).put(
        "serial:33AF6560C0000000", WheelConfig(label="Mono", filters=names, confirmed=True)
    )
    WheelStore(tmp_path).put("serial:OTHER", WheelConfig(filters=DRIVER_NAMES, confirmed=True))
    _, _, store, equipment = wheel_service(client, tmp_path)
    equipment.set_ready(Role.FILTER_WHEEL, WHEEL)
    await wait_until(lambda: store.get(("filter_wheel", "names")) == names)
    assert store.get(("filter_wheel", "label")) == "Mono"
    assert store.get(("filter_wheel", "confirmed")) is True
    assert FilterWheel(client, WHEEL).filter == "L"


async def test_a_wheel_without_serial_number_is_known_by_its_device(
    driver: Driver, tmp_path: Path
) -> None:
    client = FakeClient()
    client.responder = Driver(client)
    define_wheel(client, serial=None)
    _, _, store, equipment = wheel_service(client, tmp_path)
    equipment.set_ready(Role.FILTER_WHEEL, WHEEL)
    await wait_until(lambda: store.get(("filter_wheel", "key")) is not None)
    assert store.get(("filter_wheel", "key")) == f"device:{WHEEL}"


async def test_wheel_commands_are_checked(
    client: FakeClient, driver: Driver, tmp_path: Path
) -> None:
    service, jobs, store, equipment = wheel_service(client, tmp_path)
    equipment.set_ready(Role.FILTER_WHEEL, WHEEL)
    await wait_until(lambda: store.get(("filter_wheel", "key")) is not None)
    with pytest.raises(ValueError, match="outside"):
        service.select(6)
    with pytest.raises(ValueError, match="no filter named"):
        service.select("Lum")
    with pytest.raises(ValueError, match="5 slots"):
        await service.set_names(["L"])
    with pytest.raises(ValueError, match="two slots"):
        await service.set_names(["L", "L", "", "", ""])
    # An exposure of the main camera locks the wheel: names and filter stay as they are.
    token = jobs.reserve("expose", [Role.FILTER_WHEEL.value])
    with pytest.raises(ResourceBusyError):
        await service.set_names(["L", "R", "G", "B", "Ha"])
    with pytest.raises(ResourceBusyError):
        service.select(2)
    jobs.release(token)
