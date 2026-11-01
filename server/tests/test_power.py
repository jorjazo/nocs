# Starlette's TestClient is typed against `httpx2`; see test_api.py.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
"""Power box and weather sensor: facades and services against the recorded PPBA.

There is no INDI simulator for power boxes: the client replays what the lab's
Pegasus PPBA Gen2 defined (``dev/recordings/lab-rig-2026-10-30.xml``) and a fake
answers commands as ``indi_pegasus_ppba`` 1.4 on INDI 2.2.5 does, including its
power interface matching elements by position.
"""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from fakes import FakeClient, number_property
from fastapi.testclient import TestClient
from owner import pair_owner

from nocs.api import create_app
from nocs.api.schemas import PowerState, WeatherState
from nocs.config import Settings
from nocs.devices import DeviceError, OutputKind, PowerBox, WeatherSensor, dew_point
from nocs.equipment import DeviceConfig, OutputConfig, Profile, Role
from nocs.indi import IndiClient, PropertyState
from nocs.indi.properties import NumberElement, SwitchElement
from nocs.jobs import JobManager, ResourceBusyError
from nocs.power.service import AutoDewError, PowerCycleError, PowerService, WeatherService
from nocs.state import Json, StateStore

RECORDING = "lab-rig-2026-10-30.xml"
PPBA = "Pegasus PPBA"
POSITIONAL = ("POWER_CHANNELS", "DEW_CHANNELS", "AUTO_DEW_CONTROL", "DEW_DUTY_CYCLES")


class PpbaDriver:
    """Answers new vectors as the PPBA driver does: ``Ok`` with the new values, or ``Alert``."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.fail: set[str] = set()
        client.responder = self.respond

    def respond(self, device: str, name: str, values: Mapping[str, str | float | bool]) -> None:
        prop = self.client.get_property(device, name)
        assert prop is not None
        if name in self.fail:
            self.later(name, PropertyState.ALERT, {})
            return
        if name in POSITIONAL:
            # INDI 2.2.5's power interface: the i-th value sent sets the i-th element.
            update = dict(zip(prop.elements, values.values(), strict=False))
        else:
            update = dict(values)
        self.later(name, PropertyState.OK, update)

    def later(self, name: str, state: PropertyState, values: Mapping[str, Any]) -> None:
        text = {
            k: ("On" if v else "Off") if isinstance(v, bool) else str(v) for k, v in values.items()
        }
        asyncio.get_running_loop().call_soon(self.client.update, PPBA, name, state, text)

    def poll(self) -> None:
        """The driver's next sensor read: duty cycles come back from the 0-255 scale,
        and as 0 for a channel switched off (its PWM was set to 0)."""
        duty = self.client.get_property(PPBA, "DEW_DUTY_CYCLES")
        assert duty is not None
        on = switches(self.client, "DEW_CHANNELS")
        values = {
            name: str(int(e.value / 100 * 255) / 255 * 100 if on[name] else 0)
            for name, e in duty.elements.items()
            if isinstance(e, NumberElement)
        }
        self.client.update(PPBA, "DEW_DUTY_CYCLES", PropertyState.IDLE, values)


@pytest.fixture
def client() -> FakeClient:
    client = FakeClient()
    client.replay(RECORDING, PPBA)
    return client


@pytest.fixture
def driver(client: FakeClient) -> PpbaDriver:
    return PpbaDriver(client)


def switches(client: IndiClient, name: str) -> dict[str, bool]:
    prop = client.get_property(PPBA, name)
    assert prop is not None
    return {k: e.value for k, e in prop.elements.items() if isinstance(e, SwitchElement)}


# -- facades -----------------------------------------------------------------


def test_reads_the_recorded_ppba(client: FakeClient) -> None:
    box = PowerBox(client, PPBA)
    assert box.not_ready() == []
    assert [(o.id, o.kind, o.label, o.on) for o in box.outputs] == [
        ("dc:1", OutputKind.DC, "Enable 12V ports", True),
        ("dew:1", OutputKind.DEW, "Dew A", True),
        ("dew:2", OutputKind.DEW, "Dew B", True),
        ("variable:1", OutputKind.VARIABLE, "Adj voltage", True),
    ]
    assert box.output("dc:1").current == 0.9  # the last update recorded
    assert box.output("dew:1").duty == 0
    adjustable = box.output("variable:1")
    assert adjustable.voltage == 8
    assert adjustable.voltages == (3, 5, 8, 9, 12)
    assert box.auto_dew is True
    assert box.auto_dew_aggression == 82
    power_input = box.input
    assert power_input is not None
    assert power_input.voltage == pytest.approx(12.1)

    environment = WeatherSensor(client, PPBA).environment
    assert (environment.temperature, environment.humidity) == (26.5, 41)
    assert environment.dew_point == pytest.approx(12.2)


def test_dew_point_from_temperature_and_humidity() -> None:
    # The PPBA's own reading for 26.5 °C and 41 %.
    assert dew_point(26.5, 41) == pytest.approx(12.2, abs=0.2)
    assert dew_point(10, 0) is None
    client = FakeClient()
    client.define(
        number_property(
            "Weather", "WEATHER_PARAMETERS", WEATHER_TEMPERATURE=5, WEATHER_HUMIDITY=100
        )
    )
    assert WeatherSensor(client, "Weather").environment.dew_point == pytest.approx(5)


async def test_switching_sends_whole_vectors_in_order(
    client: FakeClient, driver: PpbaDriver
) -> None:
    box = PowerBox(client, PPBA)
    await box.set_on("dew:2", False)
    assert client.sent[-1] == (
        PPBA,
        "DEW_CHANNELS",
        {"DEW_CHANNEL_1": True, "DEW_CHANNEL_2": False},
    )
    # Matched by position, a vector with only DEW_CHANNEL_2 would have switched Dew A.
    assert switches(client, "DEW_CHANNELS") == {"DEW_CHANNEL_1": True, "DEW_CHANNEL_2": False}

    await box.set_on("dc:1", False)
    assert not box.output("dc:1").on


async def test_duty_cycle_tolerates_the_drivers_rounding(
    client: FakeClient, driver: PpbaDriver
) -> None:
    box = PowerBox(client, PPBA)
    await box.set_duty("dew:2", 50)
    assert client.sent[-1] == (PPBA, "DEW_DUTY_CYCLES", {"DEW_CHANNEL_1": 0, "DEW_CHANNEL_2": 50})
    driver.poll()
    assert box.output("dew:2").duty == pytest.approx(49.8, abs=0.1)
    with pytest.raises(ValueError, match="outside"):
        await box.set_duty("dew:1", 120)
    with pytest.raises(ValueError, match="not a dew heater"):
        await box.set_duty("dc:1", 10)


async def test_adjustable_output(client: FakeClient, driver: PpbaDriver) -> None:
    box = PowerBox(client, PPBA)
    await box.set_voltage("variable:1", 12)
    assert switches(client, "ADJOUT_VOLTAGE")["ADJOUT_12V"]
    assert box.output("variable:1").voltage == 12
    await box.set_voltage("variable:1", None)
    output = box.output("variable:1")
    assert (output.on, output.voltage) == (False, None)
    with pytest.raises(ValueError, match="cannot be set to 7 V"):
        await box.set_voltage("variable:1", 7)
    with pytest.raises(ValueError, match="switched by its voltage"):
        await box.set_on("variable:1", True)


async def test_auto_dew_and_failures(client: FakeClient, driver: PpbaDriver) -> None:
    box = PowerBox(client, PPBA)
    await box.set_auto_dew(False)
    assert box.auto_dew is False
    driver.fail.add("POWER_CHANNELS")
    with pytest.raises(DeviceError, match="POWER_CHANNELS failed"):
        await box.set_on("dc:1", False)
    with pytest.raises(ValueError, match="no output usb:1"):
        box.output("usb:1")


# -- services ----------------------------------------------------------------


class FakeEquipment:
    def __init__(self, profile: Profile, devices: dict[Role, str]) -> None:
        self.active_profile = profile
        self.devices = devices
        self.restarted: list[Role] = []
        self._listeners: list[Callable[[], None]] = []

    def ready_device(self, role: Role) -> str | None:
        return self.devices.get(role)

    async def restart_driver(self, role: Role) -> None:
        self.restarted.append(role)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)


class FakeBridge:
    def __init__(self, client: IndiClient) -> None:
        self.client = client

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        return lambda: None


def lab_profile(outputs: dict[str, OutputConfig] | None = None) -> Profile:
    power = DeviceConfig(driver="indi_pegasus_ppba", outputs=outputs)
    weather = DeviceConfig(driver="indi_pegasus_ppba")
    return Profile(name="Lab", devices={Role.POWER: power, Role.WEATHER: weather})


@pytest.fixture
def store() -> StateStore:
    return StateStore()


@pytest.fixture
def jobs(store: StateStore) -> JobManager:
    return JobManager(store)


def make_power(
    store: StateStore, jobs: JobManager, client: FakeClient, profile: Profile
) -> PowerService:
    equipment = FakeEquipment(profile, {Role.POWER: PPBA, Role.WEATHER: PPBA})
    return PowerService(store, jobs, equipment, FakeBridge(client))  # pyright: ignore[reportArgumentType]


def output_state(store: StateStore, output_id: str) -> dict[str, Json]:
    power = store.get(("power",))
    assert isinstance(power, dict)
    outputs = power["outputs"]
    assert isinstance(outputs, list)
    for output in outputs:
        assert isinstance(output, dict)
        if output["id"] == output_id:
            return output
    raise AssertionError(output_id)


async def test_state_follows_the_box_and_the_profile(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    profile = lab_profile({"dc:1": OutputConfig(label="12 V", feeds=[Role.MAIN_CAMERA])})
    power = make_power(store, jobs, client, profile)
    equipment = FakeEquipment(profile, {Role.WEATHER: PPBA})
    weather = WeatherService(store, equipment, FakeBridge(client))  # pyright: ignore[reportArgumentType]

    state = store.get(("power",))
    PowerState.model_validate(state)
    assert output_state(store, "dc:1") | {"current": None} == {
        "id": "dc:1",
        "kind": "dc",
        "label": "12 V",
        "on": True,
        "current": None,
        "duty": None,
        "voltage": None,
        "voltages": [],
        "feeds": ["main_camera"],
    }
    assert output_state(store, "dew:1")["label"] == "Dew A"
    assert WeatherState.model_validate(store.get(("weather",))).model_dump() == {
        "device": PPBA,
        "temperature": 26.5,
        "humidity": 41,
        "dew_point": 12.2,
    }

    client.update(PPBA, "POWER_SENSORS", PropertyState.OK, {"SENSOR_VOLTAGE": "11.904"})
    assert store.get(("power", "input", "voltage")) == 11.9

    equipment.devices.clear()
    weather._refresh()  # pyright: ignore[reportPrivateUsage]
    assert store.get(("weather",)) is None
    power.close()
    weather.close()


async def test_cutting_an_output_waits_for_what_it_feeds(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    profile = lab_profile({"dc:1": OutputConfig(feeds=[Role.MAIN_CAMERA, Role.MOUNT])})
    power = make_power(store, jobs, client, profile)
    token = jobs.reserve("move", [Role.MOUNT.value])
    with pytest.raises(ResourceBusyError):
        await power.set_output("dc:1", on=False)
    assert output_state(store, "dc:1")["on"] is True
    await power.set_output("dc:1", on=False, force=True)
    assert output_state(store, "dc:1")["on"] is False
    await power.set_output("dc:1", on=True)  # switching on is never refused
    jobs.release(token)
    await power.set_output("dc:1", on=False)
    power.close()


async def test_outputs_without_feeds_wait_for_any_job(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    power = make_power(store, jobs, client, lab_profile())
    token = jobs.reserve("move", [Role.FOCUSER.value])
    with pytest.raises(ResourceBusyError):
        await power.set_output("variable:1", voltage=12)
    with pytest.raises(ResourceBusyError):
        await power.set_output("variable:1", on=False)
    await power.set_output("variable:1", voltage=8)  # unchanged: nothing to refuse
    jobs.release(token)
    await power.set_output("variable:1", on=False)
    assert output_state(store, "variable:1")["on"] is False
    await power.set_output("variable:1", voltage=5)
    assert output_state(store, "variable:1")["voltage"] == 5
    power.close()


async def test_dew_heaters_and_auto_dew(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    power = make_power(store, jobs, client, lab_profile())
    with pytest.raises(AutoDewError):
        await power.set_output("dew:1", duty=30)
    await power.set_auto_dew(False)
    assert store.get(("power", "auto_dew")) is False
    await power.set_output("dew:1", duty=30)
    assert output_state(store, "dew:1")["duty"] == 30
    await power.set_output("dew:2", on=False)
    assert output_state(store, "dew:2")["on"] is False
    with pytest.raises(ValueError, match="only takes on"):
        await power.set_output("dc:1", duty=10)
    with pytest.raises(ValueError, match="takes a voltage"):
        await power.set_output("variable:1", on=True)
    power.close()


async def test_dew_heaters_keep_their_duty_while_off(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    power = make_power(store, jobs, client, lab_profile())
    await power.set_auto_dew(False)
    await power.set_output("dew:1", duty=40)
    await power.set_output("dew:1", on=False)
    driver.poll()  # the box reads the channel back at 0 %
    assert PowerBox(client, PPBA).output("dew:1").duty == 0
    heater = output_state(store, "dew:1")
    assert (heater["on"], heater["duty"]) == (False, 40)

    sent = len(client.sent)
    await power.set_output("dew:1", duty=60)  # kept, not sent: the driver would lose it
    assert len(client.sent) == sent
    assert output_state(store, "dew:1")["duty"] == 60

    await power.set_output("dew:1", on=True)
    assert [name for _, name, _ in client.sent[sent:]] == ["DEW_CHANNELS", "DEW_DUTY_CYCLES"]
    driver.poll()
    assert output_state(store, "dew:1")["on"] is True
    assert output_state(store, "dew:1")["duty"] == 60
    power.close()


def test_power_box_profile_loads_as_power_and_weather() -> None:
    profile = Profile.model_validate(
        {"name": "Old", "devices": {"power_box": {"driver": "indi_pegasus_ppba"}}}
    )
    assert set(profile.devices) == {Role.POWER, Role.WEATHER}
    with pytest.raises(ValueError, match="only the power role has outputs"):
        Profile.model_validate(
            {"name": "Bad", "devices": {"mount": {"driver": "indi_x", "outputs": {}}}}
        )
    with pytest.raises(ValueError, match="pattern"):
        Profile.model_validate(
            {"name": "Bad", "devices": {"power": {"driver": "indi_x", "outputs": {"dc1": {}}}}}
        )


# -- API ---------------------------------------------------------------------


def test_power_endpoints_need_the_owner_and_a_box() -> None:
    with TestClient(create_app(Settings(indi_host="127.0.0.1", indi_port=1))) as http:
        assert http.put("/api/power/outputs/dc:1", json={"on": False}).status_code == 401
        pair_owner(http)
        response = http.put("/api/power/outputs/dc:1", json={"on": False})
        assert response.status_code == 503
        assert http.put("/api/power/auto-dew", json={"on": "x"}).status_code == 422
        assert http.get("/api/state").json()["state"]["power"] is None
        # Bringing a device back (ADR 0030): not while nothing is connected, never the mount.
        restart = http.post("/api/equipment/roles/focuser/restart")
        assert (restart.status_code, restart.json()["detail"]) == (
            409,
            "the profile is not connected",
        )
        cycle = http.post("/api/equipment/roles/mount/power-cycle")
        assert cycle.status_code == 409
        assert "never" in cycle.json()["detail"]
        assert http.post("/api/equipment/roles/telescope/restart").status_code == 422


async def test_power_cycling_a_device(
    store: StateStore, jobs: JobManager, client: FakeClient, driver: PpbaDriver
) -> None:
    profile = lab_profile(
        {
            "dc:1": OutputConfig(feeds=[Role.MAIN_CAMERA, Role.FILTER_WHEEL]),
            "dc:2": OutputConfig(feeds=[Role.FOCUSER, Role.MOUNT]),
        }
    )
    power = make_power(store, jobs, client, profile)
    equipment = power._equipment  # pyright: ignore[reportPrivateUsage]
    assert isinstance(equipment, FakeEquipment)
    sent = len(client.sent)

    await power.power_cycle(Role.MAIN_CAMERA, off=0, settle=0)
    assert [values["POWER_CHANNEL_1"] for _, _, values in client.sent[sent:]] == [False, True]
    assert PowerBox(client, PPBA).output("dc:1").on
    assert equipment.restarted == [Role.MAIN_CAMERA]

    # What else the output feeds must be free, but for the job asking.
    token = jobs.reserve("sequence", [Role.MAIN_CAMERA.value, Role.FILTER_WHEEL.value])
    with pytest.raises(ResourceBusyError):
        await power.power_cycle(Role.MAIN_CAMERA, off=0, settle=0)
    await power.power_cycle(Role.MAIN_CAMERA, job=token, off=0, settle=0)
    jobs.release(token)

    for role, reason in (
        (Role.MOUNT, "never"),
        (Role.FOCUSER, "also feeds the mount"),
        (Role.GUIDE_CAMERA, "no output"),
    ):
        with pytest.raises(PowerCycleError, match=reason):
            await power.power_cycle(role, off=0, settle=0)
    power.close()
