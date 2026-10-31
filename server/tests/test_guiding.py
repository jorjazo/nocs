"""PHD2: settings, the JSON-RPC client and the guiding service, against a fake PHD2."""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast

import pytest
from fakes import FakeClient, driver_info, number_property

from nocs.devices import DeviceInterface, Mount
from nocs.equipment import EquipmentService, Optics, Profile, Role
from nocs.guiding import (
    GuideRig,
    GuidingNotReadyError,
    GuidingService,
    Phd2Client,
    Phd2ConnectionError,
    Phd2Error,
    Phd2Event,
    calibration_step,
    pixel_scale,
    render,
)
from nocs.indi import IndiClient
from nocs.jobs import JobManager, ResourceBusyError
from nocs.state import StateStore

CAMERA = "ZWO CCD ASI220MM Mini"
MOUNT = "ZWO AM5"


# -- settings -----------------------------------------------------------------


def test_pixel_scale() -> None:
    assert pixel_scale(2.4, 400) == pytest.approx(1.2376, abs=1e-4)
    assert pixel_scale(2.4, 400, binning=2) == pytest.approx(2.4752, abs=1e-4)


def test_calibration_step_as_phd2_computes_it() -> None:
    # PHD2's simulator profile: 1.2376"/px at 0.5x sidereal → 25 px take 4.13 s, in 12 steps.
    assert calibration_step(2.4, 400, 0.5) == 350
    # The Duo's guide sensor (4 µm) through a 250 mm scope.
    assert calibration_step(4.0, 250, 0.5) == 950
    assert calibration_step(4.0, 250, None) == 950  # half sidereal when the mount does not say
    assert calibration_step(4.0, 250, 0.9) == 550
    # Longer pulses at high declination, but never fewer than 6 steps.
    assert calibration_step(4.0, 250, 0.5, declination=60) == 1850


def rig(**changes: Any) -> GuideRig:
    values: dict[str, Any] = {
        "camera": CAMERA,
        "mount": MOUNT,
        "pixel_size": 4.0,
        "focal_length": 250.0,
        "guide_rate": 0.5,
        "indi_host": "localhost",
        "indi_port": 7624,
    }
    return GuideRig(**(values | changes))


def test_render_writes_lines_phd2_imports() -> None:
    settings = render(rig(), "lab-rig")
    lines = settings.content.splitlines()
    assert lines[0] == "PHD Config 1"
    entries = dict(line.split("\t1\t") for line in lines[1:])
    assert all(len(line.split("\t")) == 3 for line in lines[1:])  # type 1: anything else is dropped
    assert entries["/currentProfile"] == "1"
    assert entries["/profile/1/name"] == settings.profile_name
    assert settings.profile_name.startswith("NOCS lab-rig ")
    assert entries["/profile/1/indi/INDIcam"] == CAMERA
    assert entries["/profile/1/indi/INDImount"] == MOUNT
    assert entries["/profile/1/camera/LastMenuChoice"] == f"INDI Camera [{CAMERA}]"
    assert entries["/profile/1/scope/LastMenuChoice"] == f"INDI Mount [{MOUNT}]"
    assert entries["/profile/1/camera/pixelsize"] == "4.0"
    assert entries["/profile/1/frame/focalLength"] == "250"
    assert entries["/profile/1/scope/CalibrationDuration"] == "950"
    assert entries["/profile/1/AutoLoadCalibration"] == "1"


def test_profile_name_changes_with_the_settings() -> None:
    first = render(rig(), "lab-rig")
    assert render(rig(), "lab-rig") == first
    assert render(rig(pixel_size=2.9), "lab-rig").profile_name != first.profile_name
    assert render(rig(indi_host="indi"), "lab-rig").profile_name != first.profile_name


def test_render_refuses_names_that_break_the_file() -> None:
    with pytest.raises(ValueError, match="invalid camera"):
        render(rig(camera="bad\tname"), "lab-rig")
    with pytest.raises(ValueError, match="invalid mount"):
        render(rig(mount=""), "lab-rig")


def test_guiding_through_the_imaging_optics() -> None:
    profile = Profile(
        name="Duo",
        imaging=Optics(focal_length=250, reducer=0.8),
        guiding=Optics(focal_length=120),
    )
    assert profile.guiding_optics == Optics(focal_length=120)
    duo = profile.model_copy(update={"guiding_through_imaging": True})
    assert duo.guiding_optics == Optics(focal_length=250, reducer=0.8)
    assert Profile.model_validate_json(duo.model_dump_json()).guiding_through_imaging


def test_mount_guide_rate() -> None:
    client = FakeClient()
    client.define(driver_info(MOUNT, DeviceInterface.TELESCOPE))
    assert Mount(client, MOUNT).guide_rate is None
    client.define(number_property(MOUNT, "GUIDE_RATE", RATE=0.5))  # the AM5's
    assert Mount(client, MOUNT).guide_rate == 0.5
    client.define(number_property("Sim", "GUIDE_RATE", GUIDE_RATE_NS=0.3, GUIDE_RATE_WE=0.7))
    assert Mount(client, "Sim").guide_rate == 0.7


# -- a fake PHD2 ----------------------------------------------------------------


class FakePhd2:
    """Speaks PHD2's protocol; ``shutdown`` "restarts" it with the settings file imported."""

    def __init__(self, settings_file: Path | None = None) -> None:
        self.settings_file = settings_file
        self.profile = "My own profile"
        self.state = "Stopped"
        self.equipment: dict[str, Any] = {
            "camera": {"name": f"INDI Camera [{CAMERA}]", "connected": False},
            "mount": {"name": f"INDI Mount [{MOUNT}]", "connected": False},
        }
        self.connected = False
        self.exposure_ms = 2000
        self.calibrated = False
        self.star = True
        self.calibration_fails = False
        self.settles = True
        self.hold_calibration = False
        """Calibrate until told to go on (``finish_calibration``), to cancel meanwhile."""
        self._go_on = asyncio.Event()
        self.calls: list[str] = []
        self.params: dict[str, Any] = {}
        """The last parameters of each method."""
        self.restarts = 0
        self.import_on_restart = True
        self.answer: dict[str, Callable[[Any], Any]] = {}
        self._server: asyncio.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()

    @property
    def port(self) -> int:
        assert self._server is not None
        return cast(int, self._server.sockets[0].getsockname()[1])

    async def start(self) -> None:
        self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)

    async def stop(self) -> None:
        assert self._server is not None
        self._server.close()
        self.drop()
        await self._server.wait_closed()

    def drop(self) -> None:
        for writer in list(self._writers):
            writer.close()

    def event(self, name: str, **fields: Any) -> None:
        line = json.dumps({"Event": name, "Host": "fake", "Inst": 1, **fields}).encode() + b"\r\n"
        for writer in self._writers:
            writer.write(line)

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        self.event("Version", PHDVersion="2.6.14", PHDSubver="", MsgVersion=1)
        self.event("AppState", State=self.state)
        try:
            while line := await reader.readline():
                request = json.loads(line)
                method = request["method"]
                self.calls.append(method)
                self.params[method] = request.get("params")
                response: dict[str, Any] = {"jsonrpc": "2.0", "id": request["id"]}
                if method in self.answer:
                    response["result"] = self.answer[method](request.get("params"))
                elif method == "get_app_state":
                    response["result"] = self.state
                elif method == "get_profile":
                    response["result"] = {"id": 1, "name": self.profile}
                elif method == "get_current_equipment":
                    response["result"] = self.equipment
                elif method == "get_connected":
                    response["result"] = self.connected
                elif method == "set_connected":
                    if self.state != "Stopped":  # as PHD2, even when "Selected"
                        response["error"] = {
                            "code": 1,
                            "message": "cannot disconnect equipment while capture active",
                        }
                    else:
                        self.connected = request["params"][0]
                        response["result"] = 0
                elif method == "get_pixel_scale":
                    response["result"] = 4.13
                elif method == "get_exposure":
                    response["result"] = self.exposure_ms
                elif method == "set_exposure":
                    self.exposure_ms = request["params"][0]
                    response["result"] = 0
                elif method == "loop":
                    if not self.connected:
                        response["error"] = {"code": 1, "message": "camera not connected"}
                    else:
                        response["result"] = 0
                        self.state = "Looping"
                        asyncio.get_running_loop().call_later(
                            0.02, lambda: self.event("LoopingExposures", Frame=1)
                        )
                elif method == "find_star":
                    if self.star:
                        response["result"] = [118.9, 497.6]
                    else:
                        response["error"] = {"code": 1, "message": "could not find a star"}
                elif method == "guide":
                    response["result"] = 0
                    recalibrate = request["params"]["recalibrate"]
                    asyncio.get_running_loop().create_task(self._guide(recalibrate))
                elif method == "get_calibration_data":
                    response["result"] = (
                        {
                            "calibrated": True,
                            "xAngle": 0.7,
                            "xRate": 6.169,
                            "xParity": "+",
                            "yAngle": 91.8,
                            "yRate": 5.939,
                            "yParity": "+",
                            "declination": -5.4,
                        }
                        if self.calibrated
                        else {"calibrated": False}
                    )
                elif method == "stop_capture":
                    response["result"] = 0
                    # The exposure in progress ends a little later.
                    asyncio.get_running_loop().call_later(0.1, self._stopped)
                elif method == "shutdown":
                    response["result"] = 0
                    writer.write(json.dumps(response).encode() + b"\r\n")
                    await writer.drain()
                    self._restart()
                    break
                else:
                    response["error"] = {"code": 1, "message": f"unknown method {method}"}
                writer.write(json.dumps(response).encode() + b"\r\n")
                await writer.drain()
        except ConnectionError:
            pass
        finally:
            self._writers.discard(writer)
            writer.close()

    async def _guide(self, recalibrate: bool) -> None:
        await asyncio.sleep(0.01)
        if recalibrate or not self.calibrated:
            self.state = "Calibrating"
            self.event("StartCalibration", Mount=f"INDI Mount [{MOUNT}]")
            self.event("Calibrating", dir="West", step=1, State="West step 1")
            if self.hold_calibration:
                await self._go_on.wait()
            if self.state != "Calibrating":
                return  # stopped meanwhile
            if self.calibration_fails:
                self.state = "Looping"
                self.event("CalibrationFailed", Reason="star did not move enough")
                return
            self.calibrated = True
            self.event("CalibrationComplete", Mount=f"INDI Mount [{MOUNT}]")
        self.state = "Guiding"
        self.event("StartGuiding")
        self.event("SettleBegin")
        self.event("Settling", Distance=2.3, Time=1.0, SettleTime=10.0, StarLocked=True)
        if self.settles:
            self.event("SettleDone", Status=0, TotalFrames=9, DroppedFrames=0)
        else:
            self.event("SettleDone", Status=1, Error="timed-out waiting for guider to settle")

    def replay(self, path: Path) -> None:
        """Send events PHD2 recorded (``dev/recordings/``)."""
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event["Event"] not in ("Version", "AppState"):
                self.event(event.pop("Event"), **event)

    def finish_calibration(self) -> None:
        self._go_on.set()

    def _stopped(self) -> None:
        was = self.state
        self.state = "Stopped"
        self.event("GuidingStopped" if was == "Guiding" else "LoopingExposuresStopped")

    def _restart(self) -> None:
        self.restarts += 1
        self.drop()
        if self.import_on_restart and self.settings_file is not None:
            for line in self.settings_file.read_text().splitlines():
                key, _, value = line.partition("\t1\t")
                if key == "/profile/1/name":
                    self.profile = value


@pytest.fixture
async def phd2() -> AsyncIterator[FakePhd2]:
    server = FakePhd2()
    await server.start()
    yield server
    await server.stop()


async def until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


# -- client -------------------------------------------------------------------------


async def test_client_calls_and_events(phd2: FakePhd2) -> None:
    events: list[str] = []
    async with Phd2Client("127.0.0.1", phd2.port) as client:
        client.add_listener(lambda m: events.append(m.name) if isinstance(m, Phd2Event) else None)
        assert await client.call("get_app_state") == "Stopped"
        assert await client.call("get_profile") == {"id": 1, "name": "My own profile"}
        with pytest.raises(Phd2Error, match="unknown method"):
            await client.call("frobnicate", [1])
        phd2.event("GuideStep", Frame=1)
        await until(lambda: "GuideStep" in events)
    assert events[:2] == ["Version", "AppState"]


async def test_client_fails_calls_when_phd2_goes_away(phd2: FakePhd2) -> None:
    phd2.answer["loop"] = lambda _: phd2.drop()  # gone before answering
    async with Phd2Client("127.0.0.1", phd2.port) as client:
        with pytest.raises(Phd2ConnectionError):
            await client.call("loop")
        assert not client.connected
        with pytest.raises(Phd2ConnectionError):
            await client.call("get_app_state")


# -- service ------------------------------------------------------------------------


class Equipment:
    """What the guiding service reads from the equipment service."""

    def __init__(self, profile: Profile | None) -> None:
        self.active_profile = profile
        self.active = "lab-rig" if profile is not None else None
        self.ready: dict[Role, str] = {}
        self._listeners: list[Callable[[], None]] = []

    def ready_device(self, role: Role) -> str | None:
        return self.ready.get(role)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def connect(self) -> None:
        self.ready = {Role.GUIDE_CAMERA: CAMERA, Role.MOUNT: MOUNT}
        self._notify()

    def lose(self, role: Role) -> None:
        self.ready.pop(role, None)
        self._notify()

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()


class Bridge:
    def __init__(self, client: IndiClient) -> None:
        self.client: IndiClient | None = client

    def watch(self, watcher: Callable[[IndiClient | None], None]) -> Callable[[], None]:
        return lambda: None


def indi_rig() -> FakeClient:
    client = FakeClient()
    client.define(driver_info(CAMERA, DeviceInterface.CCD | DeviceInterface.GUIDER))
    client.define(
        number_property(
            CAMERA,
            "CCD_INFO",
            CCD_MAX_X=1936,
            CCD_MAX_Y=1096,
            CCD_PIXEL_SIZE=4.0,
            CCD_PIXEL_SIZE_X=4.0,
            CCD_PIXEL_SIZE_Y=4.0,
            CCD_BITSPERPIXEL=16,
        )
    )
    client.define(driver_info(MOUNT, DeviceInterface.TELESCOPE))
    client.define(number_property(MOUNT, "GUIDE_RATE", RATE=0.5))
    return client


DUO = Profile(
    name="Lab rig",
    imaging=Optics(focal_length=250, aperture=50),
    guiding_through_imaging=True,
)


class Frames:
    """Records what the service asks the capture service to show."""

    def __init__(self) -> None:
        self.following: dict[Role, tuple[str, Callable[[], float]]] = {}

    def follow(self, role: Role, by: str, exposure: Callable[[], float]) -> None:
        self.following[role] = (by, exposure)

    def unfollow(self, role: Role) -> None:
        self.following.pop(role, None)


@contextlib.asynccontextmanager
async def running(
    phd2: FakePhd2,
    equipment: Equipment,
    settings_file: Path | None,
    store: StateStore | None = None,
    jobs: JobManager | None = None,
    frames: Frames | None = None,
) -> AsyncGenerator[tuple[GuidingService, StateStore]]:
    store = store if store is not None else StateStore()
    service = GuidingService(
        store,
        cast(EquipmentService, equipment),
        Bridge(indi_rig()),
        jobs if jobs is not None else JobManager(store),
        frames,
        host="127.0.0.1",
        port=phd2.port,
        settings_file=settings_file,
        indi_host="localhost",
        indi_port=7624,
    )
    task = asyncio.create_task(service.run())
    try:
        yield service, store
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        service.close()


def guiding(store: StateStore, *keys: str) -> Any:
    return store.get(("guiding", *keys))


async def test_service_applies_settings_by_restarting_phd2(phd2: FakePhd2, tmp_path: Path) -> None:
    settings_file = tmp_path / "phd2" / "settings.phd"
    phd2.settings_file = settings_file
    equipment = Equipment(DUO)
    async with running(phd2, equipment, settings_file) as (service, store):
        await until(lambda: guiding(store, "phd2", "connected"))
        assert guiding(store, "phd2", "version") == "2.6.14"
        await until(lambda: guiding(store, "profile") == "My own profile")
        assert guiding(store, "settings") == "none"  # nothing connected yet
        assert guiding(store, "managed")

        equipment.connect()
        expected = render(
            GuideRig(CAMERA, MOUNT, 4.0, 250.0, 0.5, "localhost", 7624), "lab-rig"
        ).profile_name
        await until(lambda: guiding(store, "settings") == "applied")
        assert guiding(store, "profile") == expected
        assert service.settings is not None
        assert service.settings.profile_name == expected
        assert settings_file.read_text() == service.settings.content
        assert phd2.restarts == 1

        # Nothing changes: no more restarts.
        equipment.connect()
        await asyncio.sleep(0.1)
        assert phd2.restarts == 1


async def test_settings_wait_until_phd2_stops(phd2: FakePhd2, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.phd"
    phd2.settings_file = settings_file
    phd2.state = "Guiding"
    equipment = Equipment(DUO)
    async with running(phd2, equipment, settings_file) as (_, store):
        await until(lambda: guiding(store, "app_state") == "Guiding")
        equipment.connect()
        await until(lambda: guiding(store, "settings") == "pending")
        assert phd2.restarts == 0
        phd2.state = "Stopped"
        phd2.event("GuidingStopped")
        await until(lambda: guiding(store, "settings") == "applied")
        assert phd2.restarts == 1


async def test_phd2_that_ignores_the_file_is_reported(phd2: FakePhd2, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.phd"
    phd2.import_on_restart = False
    equipment = Equipment(DUO)
    async with running(phd2, equipment, settings_file) as (_, store):
        equipment.connect()
        await until(lambda: guiding(store, "settings") == "failed")
        assert "PHD2_SETTINGS" in guiding(store, "error")
        assert phd2.restarts == 1


async def test_profile_without_optics_is_reported(phd2: FakePhd2, tmp_path: Path) -> None:
    equipment = Equipment(Profile(name="No optics", guiding_through_imaging=True))
    async with running(phd2, equipment, tmp_path / "settings.phd") as (service, store):
        equipment.connect()
        await until(lambda: guiding(store, "error") is not None)
        assert "imaging optics" in guiding(store, "error")
        assert guiding(store, "settings") == "none"
        assert service.settings is None
        assert phd2.restarts == 0


async def test_unmanaged_phd2_is_checked_not_changed(phd2: FakePhd2) -> None:
    phd2.equipment["camera"] = {"name": "INDI Camera [Guide Simulator]", "connected": False}
    equipment = Equipment(DUO)
    async with running(phd2, equipment, None) as (service, store):
        await until(lambda: guiding(store, "phd2", "connected"))
        assert guiding(store, "settings") == "user"
        assert not guiding(store, "managed")
        equipment.connect()
        await until(lambda: guiding(store, "error") is not None)
        assert CAMERA in guiding(store, "error")
        assert MOUNT not in guiding(store, "error")
        assert service.settings is None
        assert "shutdown" not in phd2.calls


async def test_app_state_follows_events(phd2: FakePhd2) -> None:
    async with running(phd2, Equipment(None), None) as (_, store):
        await until(lambda: guiding(store, "app_state") == "Stopped")
        phd2.event("LoopingExposures", Frame=1)
        await until(lambda: guiding(store, "app_state") == "Looping")
        phd2.state = "Guiding"
        phd2.event("Resumed")  # ambiguous: the service asks
        await until(lambda: guiding(store, "app_state") == "Guiding")
        phd2.event("StarLost")
        await until(lambda: guiding(store, "app_state") == "LostLock")


async def test_service_reconnects(phd2: FakePhd2) -> None:
    async with running(phd2, Equipment(None), None) as (_, store):
        await until(lambda: guiding(store, "phd2", "connected"))
        phd2.drop()
        await until(lambda: not guiding(store, "phd2", "connected"))
        assert guiding(store, "app_state") is None
        await until(lambda: guiding(store, "phd2", "connected"), timeout=5)


# -- the guide camera, shared with PHD2 (ADR 0023) ------------------------------------


@contextlib.asynccontextmanager
async def applied(
    phd2: FakePhd2, tmp_path: Path
) -> AsyncGenerator[tuple[GuidingService, StateStore, JobManager, Frames, Equipment]]:
    """A service whose PHD2 runs the lab rig's settings."""
    settings_file = tmp_path / "settings.phd"
    phd2.settings_file = settings_file
    store = StateStore()
    jobs, frames, equipment = JobManager(store), Frames(), Equipment(DUO)
    async with running(phd2, equipment, settings_file, store, jobs, frames) as (service, _):
        equipment.connect()
        await until(lambda: guiding(store, "settings") == "applied")
        yield service, store, jobs, frames, equipment


async def test_phd2_holds_the_guide_camera_while_connected(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, jobs, frames, _):
        assert not guiding(store, "equipment")
        await service.connect()
        assert phd2.connected
        assert guiding(store, "equipment")
        assert guiding(store, "exposure") == 2.0
        with pytest.raises(ResourceBusyError, match="guiding"):
            jobs.check_free([Role.GUIDE_CAMERA.value])
        jobs.check_free([Role.MAIN_CAMERA.value, Role.MOUNT.value])  # only the camera is held
        by, exposure = frames.following[Role.GUIDE_CAMERA]
        assert by == "phd2"
        assert exposure() == 2.0

        await service.disconnect()
        assert not phd2.connected
        assert not guiding(store, "equipment")
        assert Role.GUIDE_CAMERA not in frames.following
        jobs.check_free([Role.GUIDE_CAMERA.value])


async def test_loop_connects_and_stop_waits_for_the_exposure(
    phd2: FakePhd2, tmp_path: Path
) -> None:
    async with applied(phd2, tmp_path) as (service, store, _, frames, _):
        await service.loop(1.5)
        assert phd2.connected
        assert phd2.exposure_ms == 1500
        assert guiding(store, "exposure") == 1.5
        assert frames.following[Role.GUIDE_CAMERA][1]() == 1.5
        await until(lambda: guiding(store, "app_state") == "Looping")
        await service.stop()  # returns once PHD2 says the loop stopped
        assert guiding(store, "app_state") == "Stopped"
        await service.disconnect()  # PHD2 refuses while an exposure runs
        assert not phd2.connected
        with pytest.raises(ValueError, match="exposure"):
            await service.loop(120)


async def test_disconnect_stops_a_running_loop_first(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, _, _, _):
        await service.loop()
        await until(lambda: guiding(store, "app_state") == "Looping")
        await service.disconnect()
        stopped = phd2.calls.index("stop_capture")
        assert "set_connected" in phd2.calls[stopped:]
        assert not phd2.connected


async def test_connect_is_refused_while_nocs_uses_the_camera(
    phd2: FakePhd2, tmp_path: Path
) -> None:
    async with applied(phd2, tmp_path) as (service, store, jobs, frames, _):
        token = jobs.reserve("loop", [Role.GUIDE_CAMERA.value])
        with pytest.raises(ResourceBusyError):
            await service.connect()
        assert not phd2.connected
        assert not frames.following
        jobs.release(token)
        await service.connect()
        assert guiding(store, "equipment")


async def test_connect_needs_the_profiles_settings(phd2: FakePhd2, tmp_path: Path) -> None:
    async with running(phd2, Equipment(DUO), tmp_path / "settings.phd") as (service, store):
        await until(lambda: guiding(store, "phd2", "connected"))
        with pytest.raises(GuidingNotReadyError, match="settings"):
            await service.connect()
        assert "set_connected" not in phd2.calls


async def test_settings_wait_while_phd2_holds_its_equipment(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, _, _, equipment):
        await service.connect()
        restarts = phd2.restarts
        equipment.active_profile = DUO.model_copy(update={"imaging": Optics(focal_length=400)})
        equipment.connect()
        await until(lambda: guiding(store, "settings") == "pending")
        assert phd2.restarts == restarts
        await service.disconnect()
        await until(lambda: guiding(store, "settings") == "applied")
        assert phd2.restarts == restarts + 1


async def test_phd2_going_away_frees_the_camera(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, jobs, frames, _):
        await service.connect()
        phd2.connected = False  # as a restarted PHD2
        phd2.drop()
        await until(lambda: not guiding(store, "equipment"))
        assert not frames.following
        jobs.check_free([Role.GUIDE_CAMERA.value])
        await until(lambda: guiding(store, "phd2", "connected"))
        assert not service.equipment_connected


async def test_phd2_found_connected_holds_the_camera(phd2: FakePhd2, tmp_path: Path) -> None:
    # Connected, with NOCS's settings, before nocsd started (nocsd restarted while guiding).
    phd2.connected = True
    phd2.exposure_ms = 3000
    phd2.profile = render(
        GuideRig(CAMERA, MOUNT, 4.0, 250.0, 0.5, "localhost", 7624), "lab-rig"
    ).profile_name
    async with applied(phd2, tmp_path) as (_, store, jobs, frames, _):
        await until(lambda: guiding(store, "equipment"))
        assert guiding(store, "exposure") == 3.0
        assert Role.GUIDE_CAMERA in frames.following
        with pytest.raises(ResourceBusyError):
            jobs.check_free([Role.GUIDE_CAMERA.value])


async def test_losing_the_guide_camera_disconnects_phd2(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, _, _, equipment):
        await service.loop()
        equipment.lose(Role.GUIDE_CAMERA)
        await until(lambda: not guiding(store, "equipment"))
        assert not phd2.connected


# -- calibrate, guide, stop -------------------------------------------------------------


def job(store: StateStore, job_id: str) -> Any:
    return store.get(("jobs", job_id))


async def finished(service: GuidingService, jobs: JobManager, job_id: str) -> None:
    await asyncio.wait_for(jobs.wait(job_id), 5)


async def test_guiding_calibrates_settles_and_holds_the_mount(
    phd2: FakePhd2, tmp_path: Path
) -> None:
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        assert guiding(store, "calibration") is None
        job_id = service.guide()
        await finished(service, jobs, job_id)
        assert job(store, job_id)["state"] == "succeeded", job(store, job_id)
        assert job(store, job_id)["result"] == {"calibrated": True, "frames": 9, "dropped": 0}
        assert phd2.calls.index("loop") < phd2.calls.index("find_star") < phd2.calls.index("guide")
        assert guiding(store, "app_state") == "Guiding"
        assert guiding(store, "calibration")["ra_rate"] == 6.169
        assert service.guiding
        # Slews, parking and the pad wait while PHD2 moves the mount (ADR 0023).
        with pytest.raises(ResourceBusyError, match="mount is busy"):
            jobs.check_free([Role.MOUNT.value])

        await service.stop()
        assert guiding(store, "app_state") == "Stopped"
        assert not service.guiding
        jobs.check_free([Role.MOUNT.value])
        assert guiding(store, "equipment")  # the camera stays PHD2's until disconnecting


async def test_calibration_is_reused_unless_asked(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.calibrated = True
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        await finished(service, jobs, job_id)
        assert job(store, job_id)["result"]["calibrated"] is False
        await service.stop()
        job_id = service.guide(recalibrate=True)
        await finished(service, jobs, job_id)
        assert job(store, job_id)["result"]["calibrated"] is True


async def test_no_star_fails_and_frees_the_mount(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.star = False
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        phd2.event("LoopingExposures", Frame=2)  # find_star is tried on every new frame
        for frame in range(3, 8):
            await asyncio.sleep(0.05)
            phd2.event("LoopingExposures", Frame=frame)
        await finished(service, jobs, job_id)
        assert job(store, job_id)["state"] == "failed"
        assert "no guide star" in job(store, job_id)["error"]
        assert "guide" not in phd2.calls
        assert not service.guiding
        jobs.check_free([Role.MOUNT.value])


async def test_failed_calibration_fails_the_job(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.calibration_fails = True
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        await finished(service, jobs, job_id)
        assert "calibration failed: star did not move enough" in job(store, job_id)["error"]
        assert guiding(store, "alert")["kind"] == "error"
        await until(lambda: not service.guiding)


async def test_no_settle_fails_the_job_but_guiding_goes_on(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.calibrated, phd2.settles = True, False
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        await finished(service, jobs, job_id)
        assert job(store, job_id)["state"] == "failed"
        assert "did not settle" in job(store, job_id)["error"]
        assert guiding(store, "app_state") == "Guiding"
        assert service.guiding  # PHD2 still guides: the mount stays held


async def test_stopping_cancels_a_start(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.hold_calibration = True
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        await until(lambda: guiding(store, "app_state") == "Calibrating")
        assert "calibrating" in (job(store, job_id)["message"] or "")
        await service.stop()
        await finished(service, jobs, job_id)
        assert job(store, job_id)["state"] == "cancelled"
        assert "stop_capture" in phd2.calls
        phd2.finish_calibration()
        await until(lambda: not service.guiding)
        jobs.check_free([Role.MOUNT.value])


async def test_guiding_waits_for_a_mount_nocs_moves(phd2: FakePhd2, tmp_path: Path) -> None:
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        token = jobs.reserve("move", [Role.MOUNT.value])  # the slew pad
        job_id = service.guide()
        await finished(service, jobs, job_id)
        assert "mount is busy" in job(store, job_id)["error"]
        assert "guide" not in phd2.calls
        jobs.release(token)


async def test_alerts_show_in_the_state(phd2: FakePhd2) -> None:
    async with running(phd2, Equipment(None), None) as (_, store):
        await until(lambda: guiding(store, "phd2", "connected"))
        phd2.event("Alert", Msg="Image scale changed", Type="warning")
        await until(lambda: guiding(store, "alert") is not None)
        assert guiding(store, "alert")["message"] == "Image scale changed"
        assert guiding(store, "alert")["kind"] == "warning"


async def test_guide_stars_are_picked_away_from_the_edges(phd2: FakePhd2, tmp_path: Path) -> None:
    phd2.calibrated = True
    async with applied(phd2, tmp_path) as (service, _, jobs, _, _):
        await finished(service, jobs, service.guide())
        # 1936 x 1096 (the ASI220MM Mini): 10 % of the short side kept clear.
        assert phd2.params["find_star"] == {"roi": [110, 110, 1716, 876]}


async def test_calibration_gives_up_on_a_lost_star(
    phd2: FakePhd2, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("nocs.guiding.service.LOST_WHILE_CALIBRATING", 0.2)
    phd2.exposure_ms = 10
    phd2.hold_calibration = True  # it never completes: clouds came
    async with applied(phd2, tmp_path) as (service, store, jobs, _, _):
        job_id = service.guide()
        await until(lambda: guiding(store, "app_state") == "Calibrating")
        for _ in range(10):
            phd2.event("StarLost", Frame=1, Status="Star lost - low HFD")
            await asyncio.sleep(0.05)
        await finished(service, jobs, job_id)
        assert "lost the guide star" in job(store, job_id)["error"]
        assert "stop_capture" in phd2.calls
        assert guiding(store, "alert")["message"].startswith("star lost")


async def test_guiding_statistics_from_a_recorded_session(phd2: FakePhd2, tmp_path: Path) -> None:
    recording = Path(__file__).parents[2] / "dev" / "recordings"
    async with applied(phd2, tmp_path) as (service, store, _, _, _):
        await service.connect()
        assert guiding(store, "pixel_scale") == 4.13
        assert guiding(store, "stats") is None
        phd2.replay(recording / "phd2-simulators-2026-10-31.jsonl")
        await until(lambda: guiding(store, "app_state") == "Stopped" and guiding(store, "stats"))
        await until(lambda: guiding(store, "stats", "seq") == service.history.last_seq)
        stats = guiding(store, "stats")
        recent = service.history.recent_rms()
        assert recent is not None
        assert stats["steps"] == recent.count
        assert stats["rms_ra_px"] == round(recent.ra, 3)
        assert stats["rms_ra"] == round(recent.ra * 4.13, 3)
        assert stats["rms_total"] == round(recent.total * 4.13, 3)
        assert stats["last"]["kind"] == "step"
        kinds = [e.kind for e in service.history.after(0)]
        assert (kinds.count("step"), kinds.count("dither")) == (58, 1)
        assert not guiding(store, "settling")
