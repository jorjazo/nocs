"""The Visitors view's downloads: what the viewer shows, as a full-size JPEG.

Observers may fetch them (``api/auth.py``): a visitor keeps the picture of the night,
not the FITS, and the JPEG says nothing of where the box is.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from concurrent.futures.process import BrokenProcessPool

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from nocs.imaging.pictures import NothingToShowError, Picture, Pictures
from nocs.imaging.worker import WorkerClosedError


def visit_router(pictures: Callable[[], Pictures]) -> APIRouter:
    router = APIRouter(prefix="/api/visit")

    @router.get("/frame.jpg")
    async def frame() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """The main camera's latest frame, at its full size."""
        return _send(await _picture(pictures().frame))

    @router.get("/stack.jpg")
    async def stack() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """The live stack as it stands, with its look, at its full size."""
        return _send(await _picture(pictures().stack))

    return router


async def _picture(get: Callable[[], Awaitable[Picture]]) -> Picture:
    try:
        return await get()
    except NothingToShowError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except (BrokenProcessPool, WorkerClosedError) as e:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the imaging worker is not available"
        ) from e
    except OSError as e:
        raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, str(e)) from e


def _send(picture: Picture) -> FileResponse:
    # Each picture has a file of its own: the next one is another file.
    return FileResponse(
        picture.path,
        media_type="image/jpeg",
        filename=picture.name,
        headers={"Cache-Control": "no-store"},
    )
