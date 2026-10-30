"""HTTP and WebSocket API of nocsd."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass

import anyio
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from nocs import __version__
from nocs.api.schemas import (
    CameraRoleName,
    CameraSettingsRequest,
    ConnectRequest,
    CoolingRequest,
    Driver,
    ExposeRequest,
    Health,
    Hello,
    JobStarted,
    PatchMessage,
    SerialPortInfo,
    ServerMessage,
    SetPropertyRequest,
    SnapshotMessage,
    StateSnapshot,
)
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
from nocs.imaging import (
    FRAME_TYPES,
    CameraNotReadyError,
    CameraSettings,
    CaptureService,
    image_connector,
)
from nocs.indi.drivers import DriverFifo, load_catalog
from nocs.jobs import JobManager, ResourceBusyError
from nocs.services.indi_bridge import IndiBridge, NotConnectedError
from nocs.state import Resync, StateStore

log = logging.getLogger(__name__)

_HELLO_TIMEOUT = 5.0


def create_app(settings: Settings, store: StateStore | None = None) -> FastAPI:
    store = store if store is not None else StateStore()
    bridge = IndiBridge(store, settings.indi_host, settings.indi_port)
    fifo = DriverFifo(settings.indi_fifo) if settings.indi_fifo is not None else None
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

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        services.jobs = JobManager(store)
        services.equipment = EquipmentService(
            store, ProfileStore(settings.config_dir), bridge, fifo
        )
        services.capture = CaptureService(
            store,
            services.jobs,
            services.equipment,
            bridge,
            image_connector(settings.indi_host, settings.indi_port),
            settings.data_dir,
        )
        task = asyncio.create_task(bridge.run(), name="indi-bridge")
        try:
            yield
        finally:
            await jobs().close()
            await capture().close()
            await equipment().close()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="NOCS", version=__version__, lifespan=lifespan)

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
        with _camera_errors():
            job_id = capture().expose(Role(role), request.exposure, frame_type, request.save)
        return JobStarted(job=job_id)

    @app.get("/api/indi/drivers")
    async def drivers() -> list[Driver]:  # pyright: ignore[reportUnusedFunction]
        catalog = await anyio.to_thread.run_sync(load_catalog, settings.indi_drivers_dir)
        return [Driver(**asdict(entry)) for entry in catalog]

    @app.get("/api/system/serial-ports")
    async def ports() -> list[SerialPortInfo]:  # pyright: ignore[reportUnusedFunction]
        return [SerialPortInfo(path=p.path, device=p.device) for p in serial_ports()]

    @app.websocket("/api/ws")
    async def ws(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
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
        await _stream_state(websocket, store, since)

    if settings.web_dir is not None and settings.web_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_dir, html=True), name="web")

    return app


@dataclass
class _Services:
    jobs: JobManager | None = None
    equipment: EquipmentService | None = None
    capture: CaptureService | None = None


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


async def _stream_state(websocket: WebSocket, store: StateStore, since: int | None) -> None:
    """Send the client what it is missing, then every change as it happens."""
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

            group.start_soon(sender)
            group.start_soon(receiver)
    except* WebSocketDisconnect:
        pass  # the client went away while we were sending
    except* Exception as errors:
        log.warning("websocket closed with error: %r", errors.exceptions)
    finally:
        subscription.close()
