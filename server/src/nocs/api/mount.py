"""Mount commands, the client clock report, and the slew pad's WebSocket (ADR 0015)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

import anyio
from fastapi import APIRouter, HTTPException, Response, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError

from nocs.api.auth import REVOKED, Sockets, identity
from nocs.api.schemas import (
    ClockReport,
    ClockRequest,
    EquatorialGoto,
    GotoRequest,
    JobStarted,
    MountMotion,
    MountSiteRequest,
    PadRequest,
    PadStatusMessage,
    TrackingRequest,
)
from nocs.clock import Clock
from nocs.devices import DeviceError, Direction, Motion
from nocs.jobs import ResourceBusyError
from nocs.mount.pad import PadCommand, PadStatus, drive
from nocs.mount.service import MountNotReadyError, MountService, PointingError


def mount_router(
    mount: Callable[[], MountService], clock: Callable[[], Clock], sockets: Sockets
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/clock")
    async def report_clock(request: ClockRequest) -> ClockReport:  # pyright: ignore[reportUnusedFunction]
        try:
            offset = clock().report(request.utc, request.utc_offset)
        except ValueError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
        return ClockReport(offset=round(offset, 3), corrected=clock().corrected)

    @router.post("/mount/goto", status_code=status.HTTP_202_ACCEPTED)
    async def goto(request: GotoRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            if isinstance(request, EquatorialGoto):
                job = mount().goto(request.ra, request.dec, request.frame, force=request.force)
            else:
                job = mount().goto_horizontal(request.alt, request.az)
        return JobStarted(job=job)

    @router.post("/mount/abort", status_code=status.HTTP_202_ACCEPTED)
    async def abort() -> None:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            await mount().abort()

    @router.put("/mount/tracking", status_code=status.HTTP_204_NO_CONTENT)
    async def tracking(request: TrackingRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            await mount().set_tracking(request.on, request.mode)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/mount/park", status_code=status.HTTP_202_ACCEPTED)
    async def park() -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            return JobStarted(job=mount().park())

    @router.post("/mount/unpark", status_code=status.HTTP_204_NO_CONTENT)
    async def unpark() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            await mount().unpark()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/mount/home", status_code=status.HTTP_202_ACCEPTED)
    async def home() -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            return JobStarted(job=mount().home())

    @router.post("/mount/time", status_code=status.HTTP_204_NO_CONTENT)
    async def mount_time() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Set the mount's clock now (NOCS also does it whenever the mount connects)."""
        with _mount_errors():
            await mount().send_time()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/mount/site", status_code=status.HTTP_204_NO_CONTENT)
    async def mount_site(request: MountSiteRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _mount_errors():
            await mount().send_site(request.site)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.websocket("/mount/pad")
    async def pad(websocket: WebSocket) -> None:  # pyright: ignore[reportUnusedFunction]
        who = identity(websocket)
        with sockets.track(who) as revoked:
            await websocket.accept()
            service = mount()
            pad = service.pad(who.device.name if who.device is not None else "a client")

            async def receive() -> PadCommand | None:
                try:
                    text = await websocket.receive_text()
                except WebSocketDisconnect:
                    return None
                try:
                    request = PadRequest.model_validate_json(text)
                except ValidationError as e:
                    raise ValueError(str(e.errors()[0]["msg"])) from e
                motion = Motion(
                    Direction(request.ns) if request.ns else None,
                    Direction(request.we) if request.we else None,
                )
                return PadCommand(motion, request.rate)

            async def send(pad_status: PadStatus) -> None:
                message = PadStatusMessage(
                    moving=MountMotion(
                        ns=pad_status.motion.ns.value if pad_status.motion.ns else None,  # pyright: ignore[reportArgumentType]
                        we=pad_status.motion.we.value if pad_status.motion.we else None,  # pyright: ignore[reportArgumentType]
                    ),
                    rate=pad_status.rate,
                    latched=pad_status.latched,
                    message=pad_status.message,
                )
                # A client that is gone gets nothing; receive() notices and ends the pad.
                with contextlib.suppress(WebSocketDisconnect):
                    await websocket.send_text(message.model_dump_json())

            try:
                async with anyio.create_task_group() as group:

                    async def run() -> None:
                        await drive(pad, receive, send)
                        group.cancel_scope.cancel()

                    async def watcher() -> None:
                        await revoked.wait()
                        group.cancel_scope.cancel()

                    group.start_soon(run)
                    group.start_soon(watcher)
            finally:
                service.close_pad(pad)
            if revoked.is_set():
                with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                    await websocket.close(REVOKED, "revoked")

    return router


@contextlib.contextmanager
def _mount_errors() -> Generator[None]:
    """Map failures of mount commands to HTTP errors."""
    try:
        yield
    except (ResourceBusyError, PointingError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except MountNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
