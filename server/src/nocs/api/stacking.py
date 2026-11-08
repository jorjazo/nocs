"""Live stacking (ADR 0039): the switch, a new stack, the look, saving; ``stack`` shows it."""

from __future__ import annotations

from collections.abc import Callable

import anyio
from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import FileResponse

from nocs.api.schemas import StackSaved, StackSwitchRequest
from nocs.stacking.service import LiveStackService, NothingToSaveError
from nocs.stacking.settings import StackLook
from nocs.storage import FrameUnavailableError, StorageError, StorageService


def stacking_router(
    stacking: Callable[[], LiveStackService], storage: Callable[[], StorageService]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.put("/stack", status_code=status.HTTP_204_NO_CONTENT)
    async def switch(body: StackSwitchRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Stack the main camera's lights as they arrive, or stop: every stack ends (and
        is saved when it has frames enough)."""
        await stacking().set_on(body.on)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/stack/reset", status_code=status.HTTP_204_NO_CONTENT)
    async def reset() -> Response:  # pyright: ignore[reportUnusedFunction]
        """End the stack (saved when it has frames enough): the next frame starts a new one."""
        await stacking().reset()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/stack/look", status_code=status.HTTP_204_NO_CONTENT)
    async def look(body: StackLook) -> Response:  # pyright: ignore[reportUnusedFunction]
        """How the stack is shown; the current stack is shown with it at once."""
        await stacking().set_look(body)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/stack/save")
    async def save() -> StackSaved:  # pyright: ignore[reportUnusedFunction]
        """Save the stack as it is now (FITS and JPEG); it goes on stacking."""
        try:
            saved = await stacking().save()
        except NothingToSaveError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        except StorageError as e:
            raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(e)) from e
        return StackSaved(id=saved.id, path=str(saved.relative), url=f"/api/frames/{saved.id}/file")

    @router.get("/frames/{frame_id}/image")
    async def image(frame_id: int) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """A saved live stack's stretched JPEG, next to its FITS."""
        try:
            row, path = await anyio.to_thread.run_sync(storage().frame_file, frame_id)
        except KeyError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no frame {frame_id}") from e
        except (FrameUnavailableError, FileNotFoundError) as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
        jpeg = path.with_suffix(".jpg")
        if row.frame_type != "stack" or not await anyio.Path(jpeg).is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no image for this frame")
        return FileResponse(jpeg, media_type="image/jpeg", filename=jpeg.name)

    return router
