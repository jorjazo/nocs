"""HTTP and WebSocket API of nocsd."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Annotated

import anyio
from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from nocs import __version__
from nocs.api.accessories import accessories_router
from nocs.api.auth import REVOKED, AuthMiddleware, Sockets, auth_router, identity
from nocs.api.guiding import guiding_router
from nocs.api.mount import mount_router
from nocs.api.power import power_router
from nocs.api.schemas import (
    AutofocusRun,
    CameraRoleName,
    CameraSettingsRequest,
    ConnectRequest,
    CoolingRequest,
    DestinationRequest,
    Driver,
    EjectRequest,
    ExposeRequest,
    FrameGuiding,
    FrameRecord,
    FrameTypeName,
    Health,
    Hello,
    JobStarted,
    LoopRequest,
    NightGroup,
    NightInfo,
    PatchMessage,
    SerialPortInfo,
    ServerMessage,
    SetPropertyRequest,
    SnapshotMessage,
    StateSnapshot,
    TargetRequest,
    TemperatureRecord,
    TemplateRequest,
)
from nocs.api.sequences import sequences_router
from nocs.api.solver import solver_router
from nocs.api.system import system_router
from nocs.auth import AuthStore
from nocs.clock import Clock
from nocs.config import Settings
from nocs.devices import DeviceError
from nocs.devices.camera import Region
from nocs.equipment import (
    EquipmentBusyError,
    EquipmentService,
    Profile,
    ProfileError,
    ProfileStore,
    Role,
    serial_ports,
)
from nocs.equipment.profiles import FocusSweep, Site
from nocs.filters.service import FilterWheelService
from nocs.filters.wheels import WheelStore
from nocs.focus.autofocus import AutofocusService
from nocs.focus.focusers import FocuserStore
from nocs.focus.service import FocuserService
from nocs.guiding import GuidingService, Settle
from nocs.imaging import (
    FRAME_TYPES,
    CameraNotReadyError,
    CameraSettings,
    CaptureService,
    image_connector,
)
from nocs.imaging.capture import DitherPlan, UploadDirs
from nocs.imaging.worker import ImageWorker
from nocs.indi.drivers import DriverFifo, load_catalog
from nocs.jobs import JobManager, ResourceBusyError
from nocs.mount.service import MountNotReadyError, MountService
from nocs.pointing import CenteringService, PointingService
from nocs.power.service import PowerService, WeatherService
from nocs.sequence import CheckpointFile, SequenceStore
from nocs.sequence.rig import Parts
from nocs.sequence.service import SequenceService
from nocs.services import watchdog
from nocs.services.gps import GpsService, NoFixError
from nocs.services.indi_bridge import IndiBridge, NotConnectedError
from nocs.services.system import OperationUnavailableError, SystemService
from nocs.services.timekeeping import TimeKeeper
from nocs.solving import Astap, SolverService
from nocs.state import Resync, StateStore
from nocs.storage import (
    FocusRun,
    FrameFilter,
    FrameUnavailableError,
    Located,
    NightRow,
    StorageError,
    StorageService,
)
from nocs.storage.environment import EnvironmentLog
from nocs.storage.layout import clean
from nocs.storage.service import DriveBusyError, EjectUnavailableError
from nocs.system.client import HelperUnavailableError
from nocs.system.protocol import HelperError

log = logging.getLogger(__name__)

_HELLO_TIMEOUT = 5.0


def create_app(settings: Settings, store: StateStore | None = None) -> FastAPI:
    store = store if store is not None else StateStore()

    async def restart_hung_indiserver() -> None:
        """Where nocs-system can restart services: a hung indiserver gets in the way of
        everything, so it is restarted whatever runs (ADR 0030)."""
        if services.system is not None and services.system.offers("services.restart"):
            await services.system.restart_service("indiserver", force=True)

    bridge = IndiBridge(
        store, settings.indi_host, settings.indi_port, on_hung=restart_hung_indiserver
    )
    fifo = DriverFifo(settings.indi_fifo) if settings.indi_fifo is not None else None
    auth = AuthStore(settings.config_dir / "auth.json")
    sockets = Sockets()
    # Created in the lifespan: they publish to the store and spawn tasks on its loop.
    services = _Services()

    def equipment() -> EquipmentService:
        assert services.equipment is not None
        return services.equipment

    def jobs() -> JobManager:
        assert services.jobs is not None
        return services.jobs

    def capture() -> CaptureService:
        assert services.capture is not None
        return services.capture

    def storage() -> StorageService:
        assert services.storage is not None
        return services.storage

    def mount() -> MountService:
        assert services.mount is not None
        return services.mount

    def clock() -> Clock:
        assert services.clock is not None
        return services.clock

    def power() -> PowerService:
        assert services.power is not None
        return services.power

    def focuser() -> FocuserService:
        assert services.focuser is not None
        return services.focuser

    def filter_wheel() -> FilterWheelService:
        assert services.filter_wheel is not None
        return services.filter_wheel

    def guiding() -> GuidingService:
        assert services.guiding is not None
        return services.guiding

    def autofocus() -> AutofocusService:
        assert services.autofocus is not None
        return services.autofocus

    def system() -> SystemService:
        assert services.system is not None
        return services.system

    def pointing() -> PointingService:
        assert services.pointing is not None
        return services.pointing

    def centering() -> CenteringService:
        assert services.centering is not None
        return services.centering

    def sequences() -> SequenceService:
        assert services.sequences is not None
        return services.sequences

    def sequence_parts() -> Parts:
        return Parts(
            capture=capture(),
            filters=filter_wheel(),
            focus=autofocus(),
            mount=mount(),
            guiding=guiding(),
            power=power(),
        )

    def site_longitude() -> float | None:
        profile = equipment().active_profile
        return profile.site.longitude if profile is not None and profile.site else None

    def imaging_sweep() -> FocusSweep | None:
        """From the profile as saved: a new sweep needs no reconnection."""
        active = equipment().active
        profile = ProfileStore(settings.config_dir).get(active) if active else None
        return profile.imaging.autofocus if profile and profile.imaging else None

    async def record_focus_run(run: FocusRun) -> None:
        await anyio.to_thread.run_sync(storage().add_focus_run, run)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        services.clock = Clock(store)
        services.jobs = JobManager(store)
        services.system = SystemService(store, services.jobs, settings.system_socket)
        services.equipment = EquipmentService(
            store, ProfileStore(settings.config_dir), bridge, fifo
        )
        services.worker = ImageWorker(settings.data_dir / "previews")
        services.worker.start()
        services.storage = StorageService(
            store,
            settings.config_dir,
            settings.data_dir,
            settings.storage_dir or settings.data_dir,
            site_longitude,
            now=services.clock.now,
            helper=services.system,
            busy=services.jobs.active,
        )
        await services.system.refresh()  # so that drives plugged in already get mounted
        await services.storage.start()
        services.capture = CaptureService(
            store,
            services.jobs,
            services.equipment,
            bridge,
            image_connector(settings.indi_host, settings.indi_port),
            services.worker,
            services.storage,
            settings.data_dir,
            _upload_dirs(settings),
            services.clock,
        )
        services.mount = MountService(
            store, services.jobs, services.equipment, bridge, services.clock
        )
        services.power = PowerService(store, services.jobs, services.equipment, bridge)
        services.weather = WeatherService(store, services.equipment, bridge)
        services.focuser = FocuserService(
            store, services.jobs, services.equipment, bridge, FocuserStore(settings.config_dir)
        )
        services.autofocus = AutofocusService(
            store,
            services.jobs,
            services.focuser,
            services.capture,
            sweep=imaging_sweep,
            profile=lambda: equipment().active,
            record=record_focus_run,
        )
        services.environment = EnvironmentLog(store, services.storage, services.clock.now)
        services.environment.start()
        services.filter_wheel = FilterWheelService(
            store, services.jobs, services.equipment, bridge, WheelStore(settings.config_dir)
        )
        services.solver = SolverService(store, Astap.find(settings.astap, settings.astap_db))
        await services.solver.start()
        services.guiding = GuidingService(
            store,
            services.equipment,
            bridge,
            services.jobs,
            services.capture,
            host=settings.phd2_host,
            port=settings.phd2_port,
            settings_file=settings.phd2_settings,
            indi_host=settings.phd2_indi_host or settings.indi_host,
            indi_port=settings.phd2_indi_port or settings.indi_port,
        )
        services.pointing = PointingService(
            store, services.jobs, services.capture, services.solver, services.mount
        )
        services.centering = CenteringService(
            store, services.jobs, services.pointing, services.mount
        )
        services.capture.use_guider(services.guiding)
        services.sequences = SequenceService(
            store,
            services.jobs,
            SequenceStore(settings.config_dir),
            CheckpointFile(settings.data_dir / "sequence" / "run.json"),
            services.clock,
            sequence_parts,
        )
        task = asyncio.create_task(bridge.run(), name="indi-bridge")
        guiding_task = asyncio.create_task(services.guiding.run(), name="phd2")
        system_task = asyncio.create_task(services.system.run(), name="nocs-system")
        time_keeper = TimeKeeper(services.clock, services.jobs, services.system)
        time_task = asyncio.create_task(time_keeper.run(), name="timekeeping")
        services.gps = GpsService(store, services.equipment, settings.gpsd_host, settings.gpsd_port)
        gps_task = asyncio.create_task(services.gps.run(), name="gpsd")
        watchdog_task = asyncio.create_task(watchdog.run(), name="systemd-watchdog")
        try:
            yield
        finally:
            for background in (watchdog_task, gps_task, time_task, system_task, guiding_task):
                background.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await background
            services.guiding.close()
            await mount().close()
            power().close()
            services.weather.close()
            await services.environment.close()
            await focuser().close()
            await filter_wheel().close()
            await jobs().close()
            await capture().close()
            await equipment().close()
            await storage().close()
            services.worker.close()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="NOCS", version=__version__, lifespan=lifespan)
    app.add_middleware(AuthMiddleware, auth=auth, hostnames=settings.hostnames)
    app.include_router(auth_router(auth, sockets))
    app.include_router(mount_router(mount, clock, sockets, guiding))
    app.include_router(power_router(power))
    app.include_router(guiding_router(guiding))
    app.include_router(system_router(system))
    app.include_router(solver_router(pointing, centering))
    app.include_router(accessories_router(focuser, filter_wheel, autofocus))
    app.include_router(sequences_router(sequences))

    @app.get("/api/autofocus/runs")
    async def focus_runs(  # pyright: ignore[reportUnusedFunction]
        before: int | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 20
    ) -> list[AutofocusRun]:
        with _catalog_errors():
            runs = await anyio.to_thread.run_sync(storage().focus_runs, limit, before)
        return [_focus_run(run) for run in runs]

    @app.get("/api/temperatures")
    async def temperatures(  # pyright: ignore[reportUnusedFunction]
        since: datetime | None = None, until: datetime | None = None
    ) -> list[TemperatureRecord]:
        """Samples from ``since`` (default: 12 hours ago) to ``until``, oldest first."""
        start = since or clock().now() - timedelta(hours=12)
        with _catalog_errors():
            samples = await anyio.to_thread.run_sync(
                storage().temperatures, _iso(start), _iso(until) if until else None
            )
        return [TemperatureRecord(**dataclasses.asdict(sample)) for sample in samples]

    @app.get("/api/health")
    async def health() -> Health:  # pyright: ignore[reportUnusedFunction]
        return Health(version=__version__, indi_connected=bridge.client is not None)

    @app.get("/api/state")
    async def state() -> StateSnapshot:  # pyright: ignore[reportUnusedFunction]
        return StateSnapshot(version=store.version, state=store.snapshot())

    @app.post("/api/indi/devices/{device}/properties/{name}", status_code=status.HTTP_202_ACCEPTED)
    async def set_property(  # pyright: ignore[reportUnusedFunction]
        device: str, name: str, request: SetPropertyRequest
    ) -> None:
        try:
            await bridge.set_property(device, name, request.values)
        except NotConnectedError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e.args[0])) from e
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

    @app.get("/api/profiles")
    async def list_profiles() -> dict[str, Profile]:  # pyright: ignore[reportUnusedFunction]
        return equipment().profiles()

    @app.get("/api/profiles/{profile_id}")
    async def get_profile(profile_id: str) -> Profile:  # pyright: ignore[reportUnusedFunction]
        try:
            profile = equipment().profile(profile_id)
        except ProfileError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        if profile is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no profile {profile_id}")
        return profile

    @app.put("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def put_profile(  # pyright: ignore[reportUnusedFunction]
        profile_id: str, profile: Profile
    ) -> Response:
        try:
            equipment().save_profile(profile_id, profile)
        except ProfileError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.delete("/api/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_profile(profile_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        try:
            deleted = equipment().delete_profile(profile_id)
        except ProfileError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        except EquipmentBusyError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no profile {profile_id}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/equipment/connect", status_code=status.HTTP_202_ACCEPTED)
    async def connect(request: ConnectRequest) -> None:  # pyright: ignore[reportUnusedFunction]
        try:
            equipment().connect(request.profile)
        except (KeyError, ProfileError) as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no profile {request.profile}") from e
        except EquipmentBusyError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    @app.post("/api/equipment/disconnect", status_code=status.HTTP_202_ACCEPTED)
    async def disconnect() -> None:  # pyright: ignore[reportUnusedFunction]
        await guiding().release()  # PHD2 lets go of the camera and mount first (ADR 0023)
        equipment().disconnect()

    @app.post("/api/jobs/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_job(job_id: str) -> None:  # pyright: ignore[reportUnusedFunction]
        try:
            running = jobs().cancel(job_id)
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no job {job_id}") from e
        if not running:
            raise HTTPException(status.HTTP_409_CONFLICT, f"job {job_id} has already finished")

    @app.post("/api/cameras/{role}/settings", status_code=status.HTTP_204_NO_CONTENT)
    async def camera_settings(  # pyright: ignore[reportUnusedFunction]
        role: CameraRoleName, request: CameraSettingsRequest
    ) -> Response:
        region = request.region
        settings = CameraSettings(
            exposure=request.exposure,
            gain=request.gain,
            offset=request.offset,
            binning=request.binning,
            region=(
                Region(region.x, region.y, region.width, region.height)
                if region is not None and region != "full"
                else None
            ),
            full_frame=region == "full",
            frame_type=FRAME_TYPES[request.frame_type] if request.frame_type else None,
        )
        with _camera_errors():
            await capture().configure(Role(role), settings)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/cameras/{role}/cooling", status_code=status.HTTP_204_NO_CONTENT)
    async def camera_cooling(  # pyright: ignore[reportUnusedFunction]
        role: CameraRoleName, request: CoolingRequest
    ) -> Response:
        with _camera_errors():
            await capture().set_cooling(Role(role), request.on, request.target, request.ramp)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/cameras/{role}/expose", status_code=status.HTTP_202_ACCEPTED)
    async def camera_expose(  # pyright: ignore[reportUnusedFunction]
        role: CameraRoleName, request: ExposeRequest
    ) -> JobStarted:
        frame_type = FRAME_TYPES[request.frame_type] if request.frame_type else None
        dither = None
        if request.dither is not None:
            settle = request.dither.settle
            dither = DitherPlan(
                request.dither.every,
                request.dither.pixels,
                Settle(settle.pixels, settle.time, settle.timeout),
                request.dither.ra_only,
            )
        with _camera_errors():
            job_id = capture().expose(
                Role(role), request.exposure, frame_type, request.save, request.count, dither
            )
        return JobStarted(job=job_id)

    @app.post("/api/cameras/{role}/loop", status_code=status.HTTP_202_ACCEPTED)
    async def camera_loop(  # pyright: ignore[reportUnusedFunction]
        role: CameraRoleName, request: LoopRequest
    ) -> JobStarted:
        frame_type = FRAME_TYPES[request.frame_type] if request.frame_type else None
        with _camera_errors():
            job_id = capture().loop(Role(role), request.exposure, frame_type)
        return JobStarted(job=job_id)

    @app.get("/api/previews/{name}")
    async def preview(name: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        path = services.worker.preview_path(name) if services.worker is not None else None
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no such preview")
        # Each preview has a name of its own and never changes; only clients may keep it.
        headers = {"Cache-Control": "private, max-age=31536000, immutable"}
        return FileResponse(path, media_type="image/jpeg", headers=headers)

    @app.put("/api/storage/destination", status_code=status.HTTP_204_NO_CONTENT)
    async def storage_destination(  # pyright: ignore[reportUnusedFunction]
        request: DestinationRequest,
    ) -> Response:
        try:
            await storage().choose(request.destination)
        except StorageError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/gps/site")
    async def gps_site() -> Site:  # pyright: ignore[reportUnusedFunction]
        """Make the GPS's position the active profile's site, and the mount's (ADR 0029)."""
        assert services.gps is not None
        try:
            site = services.gps.apply_site()
        except NoFixError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        except ProfileError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        try:
            await mount().send_site(site)
        except (MountNotReadyError, ResourceBusyError, DeviceError) as e:
            # It gets the profile's site whenever it becomes ready, or with the next go to.
            log.info("the mount keeps its site for now: %s", e)
        return site

    @app.post(
        "/api/storage/destinations/{destination_id}/eject",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def storage_eject(  # pyright: ignore[reportUnusedFunction]
        destination_id: str, request: EjectRequest | None = None
    ) -> Response:
        """Unmount a USB drive and power it off, so it can be unplugged (ADR 0027)."""
        try:
            await storage().eject(destination_id, force=request is not None and request.force)
        except DriveBusyError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        except (EjectUnavailableError, HelperUnavailableError, OperationUnavailableError) as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        except HelperError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
        except StorageError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put("/api/storage/target", status_code=status.HTTP_204_NO_CONTENT)
    async def storage_target(request: TargetRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        try:
            await storage().set_target(request.target)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.put("/api/storage/template", status_code=status.HTTP_204_NO_CONTENT)
    async def storage_template(  # pyright: ignore[reportUnusedFunction]
        request: TemplateRequest,
    ) -> Response:
        try:
            await storage().set_template(request.template)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/nights")
    async def nights() -> list[NightInfo]:  # pyright: ignore[reportUnusedFunction]
        with _catalog_errors():
            rows = await anyio.to_thread.run_sync(storage().nights)
        return [_night_info(row) for row in rows]

    @app.get("/api/frames")
    async def frames(  # pyright: ignore[reportUnusedFunction]
        night: int | None = None,
        target: str | None = None,
        type: FrameTypeName | None = None,
        filter: str | None = None,
        before: int | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> list[FrameRecord]:
        query = FrameFilter(night, target, type, filter, before, limit)
        with _catalog_errors():
            found = await anyio.to_thread.run_sync(storage().frames, query)
        return [_frame_record(frame) for frame in found]

    @app.get("/api/frames/{frame_id}/file")
    async def frame_file(frame_id: int) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        with _catalog_errors():
            _, path = await anyio.to_thread.run_sync(storage().frame_file, frame_id)
        # Starlette answers range requests, so interrupted downloads can resume.
        return FileResponse(path, media_type="application/fits", filename=path.name)

    @app.get("/api/nights/{night_id}/zip")
    async def night_zip(  # pyright: ignore[reportUnusedFunction]
        night_id: int,
        target: str | None = None,
        type: FrameTypeName | None = None,
        filter: str | None = None,
    ) -> StreamingResponse:
        service = storage()
        with _catalog_errors():
            found = await anyio.to_thread.run_sync(service.nights, night_id)
            if not found:
                raise KeyError(night_id)
            query = FrameFilter(night=night_id, target=target, frame_type=type, filter=filter)
            frames = await anyio.to_thread.run_sync(service.frames, query)
            size, chunks = await anyio.to_thread.run_sync(service.zip, frames)
        name = "_".join(
            part
            for part in ("NOCS", found[0].night, type, clean(target or ""), clean(filter or ""))
            if part
        )
        headers = {
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="{name}.zip"',
        }
        # A plain iterator: Starlette reads it in a worker thread, off the event loop.
        return StreamingResponse(chunks, media_type="application/zip", headers=headers)

    @app.get("/api/indi/drivers")
    async def drivers() -> list[Driver]:  # pyright: ignore[reportUnusedFunction]
        catalog = await anyio.to_thread.run_sync(load_catalog, settings.indi_drivers_dir)
        return [Driver(**asdict(entry)) for entry in catalog]

    @app.get("/api/system/serial-ports")
    async def ports() -> list[SerialPortInfo]:  # pyright: ignore[reportUnusedFunction]
        return [SerialPortInfo(path=p.path, device=p.device) for p in serial_ports()]

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        with sockets.track(identity(websocket)) as revoked:
            await websocket.accept()
            hello = Hello()
            try:
                with anyio.move_on_after(_HELLO_TIMEOUT):
                    hello = Hello.model_validate_json(await websocket.receive_text())
            except ValidationError:
                pass
            except WebSocketDisconnect:
                return
            since = hello.since if hello.epoch == store.epoch else None
            await _stream_state(websocket, store, since, revoked)

    if settings.web_dir is not None and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app


@dataclass
class _Services:
    worker: ImageWorker | None = None
    jobs: JobManager | None = None
    equipment: EquipmentService | None = None
    capture: CaptureService | None = None
    storage: StorageService | None = None
    mount: MountService | None = None
    power: PowerService | None = None
    weather: WeatherService | None = None
    clock: Clock | None = None
    focuser: FocuserService | None = None
    filter_wheel: FilterWheelService | None = None
    solver: SolverService | None = None
    pointing: PointingService | None = None
    centering: CenteringService | None = None
    autofocus: AutofocusService | None = None
    guiding: GuidingService | None = None
    environment: EnvironmentLog | None = None
    system: SystemService | None = None
    sequences: SequenceService | None = None
    gps: GpsService | None = None


def _iso(time: datetime) -> str:
    """As the catalog keeps times: UTC, to the second (naive times are taken as UTC)."""
    if time.tzinfo is None:
        time = time.replace(tzinfo=UTC)
    return time.astimezone(UTC).isoformat(timespec="seconds")


def _focus_run(run: FocusRun) -> AutofocusRun:
    assert run.id is not None
    fields = dataclasses.asdict(run)
    fields["run"] = json.loads(run.run)
    return AutofocusRun.model_validate(fields)


def _upload_dirs(settings: Settings) -> UploadDirs | None:
    if settings.indi_upload_dir is None:
        return None
    driver = PurePosixPath(settings.indi_upload_dir)
    local = settings.indi_upload_dir_local or Path(settings.indi_upload_dir)
    return UploadDirs(driver, local)


@contextlib.contextmanager
def _camera_errors() -> Generator[None]:
    """Map failures of camera commands to HTTP errors."""
    try:
        yield
    except ResourceBusyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except CameraNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        # The device (or indiserver) failed or refused: an upstream error.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e


@contextlib.contextmanager
def _catalog_errors() -> Generator[None]:
    """Map failures of catalog queries and downloads to HTTP errors."""
    try:
        yield
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"not in the catalog: {e}") from e
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except FrameUnavailableError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except StorageError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e


def _night_info(row: NightRow) -> NightInfo:
    groups = [
        NightGroup(
            frame_type=group.frame_type,  # pyright: ignore[reportArgumentType]
            target=group.target,
            filter=group.filter,
            frames=group.frames,
            size=group.size,
            exposure=group.exposure,
        )
        for group in row.groups
    ]
    return NightInfo(
        id=row.id,
        night=row.night,
        site=row.site,
        first_frame=row.first_frame,
        last_frame=row.last_frame,
        frames=sum(g.frames for g in groups),
        size=sum(g.size for g in groups),
        groups=groups,
        zip_url=f"/api/nights/{row.id}/zip",
    )


def _frame_record(frame: Located) -> FrameRecord:
    row = frame.row
    return FrameRecord(
        id=row.id,
        night=row.night,
        target=row.target,
        frame_type=row.frame_type,  # pyright: ignore[reportArgumentType]
        filter=row.filter,
        exposure=row.exposure,
        started=row.started,
        size=row.size,
        path=str(row.path),
        volume=row.volume_label,
        available=frame.path is not None,
        url=f"/api/frames/{row.id}/file",
        camera=row.camera,
        profile=row.profile,
        gain=row.gain,
        offset=row.offset,
        binning=row.binning,
        temperature=row.temperature,
        width=row.width,
        height=row.height,
        stars=row.stars,
        hfr=row.hfr,
        guiding=(
            FrameGuiding(
                rms_ra=row.guide_rms_ra,
                rms_dec=row.guide_rms_dec,
                rms_total=row.guide_rms_total,
                steps=row.guide_steps,
                lost=row.guide_lost or 0,
            )
            if row.guide_steps is not None
            else None
        ),
    )


async def _stream_state(
    websocket: WebSocket, store: StateStore, since: int | None, revoked: anyio.Event
) -> None:
    """Send the client what it is missing, then every change as it happens, until revoked."""
    subscription = store.subscribe()

    async def send(message: ServerMessage) -> None:
        await websocket.send_text(message.model_dump_json())

    async def sender() -> None:
        missed = store.patches_since(since) if since is not None else None
        if missed is None:
            last = store.version
            await send(SnapshotMessage(epoch=store.epoch, version=last, state=store.snapshot()))
        else:
            last = since if since is not None else 0
            for patch in missed:
                await send(PatchMessage.from_patch(patch))
                last = patch.version
        while True:
            item = await subscription.get()
            if isinstance(item, Resync):
                last = store.version
                await send(SnapshotMessage(epoch=store.epoch, version=last, state=store.snapshot()))
            elif item.version > last:
                await send(PatchMessage.from_patch(item))
                last = item.version

    # Structured with an anyio task group, the concurrency model of the ASGI server
    # itself: cancellation of this handler (shutdown, client gone) then propagates
    # exactly as the server expects, and both halves always stop together.
    try:
        async with anyio.create_task_group() as group:

            async def receiver() -> None:
                # Clients have nothing more to say yet; this only detects disconnection.
                with contextlib.suppress(WebSocketDisconnect):
                    while True:
                        await websocket.receive_text()
                group.cancel_scope.cancel()

            async def watcher() -> None:
                await revoked.wait()
                group.cancel_scope.cancel()

            group.start_soon(sender)
            group.start_soon(receiver)
            group.start_soon(watcher)
    except* WebSocketDisconnect:
        pass  # the client went away while we were sending
    except* Exception as errors:
        log.warning("websocket closed with error: %r", errors.exceptions)
    finally:
        subscription.close()
    if revoked.is_set():
        # The client may be gone already; then there is nobody to tell.
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(REVOKED, "revoked")
