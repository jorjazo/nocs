"""The Video view (lucky imaging): the main camera's stream, its preview, recordings."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

import anyio
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from nocs.api.schemas import (
    JobStarted,
    VideoRecordRequest,
    VideoRecordStarted,
    VideoSettingsRequest,
)
from nocs.devices import DeviceError
from nocs.devices.camera import Region
from nocs.imaging.capture import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.storage import StorageError
from nocs.video.service import VideoError, VideoService, VideoUnavailableError

FRAME_WAIT = 10.0
"""Seconds a request for the next preview waits for it."""


def video_router(
    video: Callable[[], VideoService], allowed: Callable[[], None] = lambda: None
) -> APIRouter:
    """``allowed`` refuses with an HTTP error while the rig is another view's (a sequence)."""
    router = APIRouter(prefix="/api/video")

    @router.post("/start", status_code=status.HTTP_202_ACCEPTED)
    async def start() -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Stream the main camera's video until stopped: a job that holds the camera."""
        allowed()
        with _errors():
            return JobStarted(job=video().start_stream())

    @router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
    async def stop() -> Response:  # pyright: ignore[reportUnusedFunction]
        video().stop_stream()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/settings", status_code=status.HTTP_204_NO_CONTENT)
    async def settings(body: VideoSettingsRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Exposure and gain apply at once; a new region or depth restarts the stream."""
        region = body.region
        with _errors():
            await video().configure(
                exposure=body.exposure,
                gain=body.gain,
                depth=body.depth,
                region=(
                    Region(region.x, region.y, region.width, region.height)
                    if region is not None and region != "full"
                    else None
                ),
                full_frame=region == "full",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/record", status_code=status.HTTP_202_ACCEPTED)
    async def record(body: VideoRecordRequest) -> VideoRecordStarted:  # pyright: ignore[reportUnusedFunction]
        """Record the stream to a SER file on the storage destination, below
        ``NOCS/<night>/Video/<target>/``. It holds the mount, the focuser and the filter
        wheel until it ends."""
        with _errors():
            return VideoRecordStarted(
                id=await video().record(seconds=body.seconds, frames=body.frames)
            )

    @router.post("/record/stop", status_code=status.HTTP_204_NO_CONTENT)
    async def stop_recording() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            await video().stop_recording()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get(
        "/frame",
        responses={200: {"content": {"image/jpeg": {}}}, 204: {"description": "None came."}},
    )
    async def frame(after: int = Query(default=0, ge=0)) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The newest preview (JPEG) once there is one newer than ``after``, or 204 after
        some seconds without one. Its number is in ``X-Frame``: ask for the next with it."""
        found: tuple[int, bytes] | None = None
        with anyio.move_on_after(FRAME_WAIT):
            found = await video().next_frame(after)
        if found is None:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        seq, jpeg = found
        headers = {"X-Frame": str(seq), "Cache-Control": "no-store"}
        return Response(jpeg, media_type="image/jpeg", headers=headers)

    @router.get("/recordings/{recording_id}")
    async def download(recording_id: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        path = video().recording_file(recording_id)
        if path is None or not await anyio.Path(path).is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no recording {recording_id}")
        return FileResponse(path, media_type="application/octet-stream", filename=path.name)

    @router.delete("/recordings/{recording_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete(recording_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        try:
            await video().delete_recording(recording_id)
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no recording {recording_id}") from e
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except (ResourceBusyError, VideoError) as e:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if isinstance(e, VideoUnavailableError)
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code, str(e)) from e
    except CameraNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except StorageError as e:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except DeviceError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
