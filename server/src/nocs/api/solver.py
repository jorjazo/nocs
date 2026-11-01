"""Plate solving commands: solve a frame of the main camera, sync the mount to it, centre;
saved frames solved for the framing chart."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import FileResponse

from nocs.align.service import PolarAlignmentService, PolarOptions
from nocs.api.schemas import (
    CenterRequest,
    JobStarted,
    PolarAlignRequest,
    SolvedFrame,
    SolvedFrames,
    SolveRequest,
)
from nocs.devices import DeviceError
from nocs.imaging import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.mount.service import MountNotReadyError, PointingError
from nocs.pointing import (
    CenteringService,
    CenterOptions,
    PointingService,
    SavedFrames,
    SolveOptions,
)
from nocs.solving import Failure, SolveError
from nocs.storage import FrameUnavailableError, StorageError


def solver_router(
    pointing: Callable[[], PointingService], centering: Callable[[], CenteringService]
) -> APIRouter:
    router = APIRouter(prefix="/api/solver")

    @router.post("/solve", status_code=status.HTTP_202_ACCEPTED)
    async def solve(request: SolveRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        if request.frame == "last":
            if request.sync or request.exposure is not None or request.binning is not None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "the last frame is solved as it is: no exposure, binning nor sync",
                )
            with _errors():
                return JobStarted(job=pointing().start_kept())
        options = SolveOptions(
            exposure=request.exposure, binning=request.binning, sync=request.sync
        )
        with _errors():
            return JobStarted(job=pointing().start(options))

    @router.post("/sync", status_code=status.HTTP_204_NO_CONTENT)
    async def sync() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Sync the mount to the last solution."""
        with _errors():
            await pointing().sync()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/center", status_code=status.HTTP_202_ACCEPTED)
    async def center(request: CenterRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Go to a J2000 target and centre it in the main camera's frame."""
        options = CenterOptions(
            tolerance=request.tolerance,
            attempts=request.attempts,
            settle=request.settle,
            method=request.method,
            exposure=request.exposure,
            binning=request.binning,
            force=request.force,
        )
        with _errors():
            return JobStarted(job=centering().start(request.ra, request.dec, options))

    return router


def saved_frames_router(saved: Callable[[], SavedFrames]) -> APIRouter:
    """The owner's solved frames, under the framing chart (phase 3.7c, ADR 0020)."""
    router = APIRouter(prefix="/api/frames")

    @router.get("/solved")
    async def solved(  # pyright: ignore[reportUnusedFunction]
        ra: Annotated[float, Query(ge=0, lt=24, description="J2000, hours.")],
        dec: Annotated[float, Query(ge=-90, le=90, description="J2000, degrees.")],
        radius: Annotated[float, Query(gt=0, le=30, description="Degrees.")] = 5.0,
        target: Annotated[
            str | None, Query(description="A target name: count its lights still to solve.")
        ] = None,
    ) -> SolvedFrames:
        """Solved frames whose centre is within ``radius`` of a point, newest first."""
        with _errors():
            found = await anyio.to_thread.run_sync(saved().near, ra, dec, radius, target)
        frames: list[SolvedFrame] = []
        for located, solution, has_image in found.solved:
            row = located.row
            width, height = solution.fov
            frames.append(
                SolvedFrame(
                    id=row.id,
                    night=row.night,
                    target=row.target,
                    filter=row.filter,
                    exposure=row.exposure,
                    started=row.started,
                    ra=solution.ra,
                    dec=solution.dec,
                    rotation=solution.rotation,
                    scale=solution.scale,
                    mirrored=solution.mirrored,
                    fov=[width, height],
                    image=f"/api/frames/{row.id}/sky.jpg" if has_image else None,
                    solved=solution.solved,
                )
            )
        return SolvedFrames(frames=frames, unsolved=found.unsolved, candidate=found.candidate)

    @router.get("/{frame_id}/sky.jpg")
    async def sky_image(frame_id: int) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        """A solved frame's JPEG, downscaled, as NOCS shows the frame."""
        path = saved().image(frame_id)
        if path is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no image of frame {frame_id}")
        # A frame's id is never reused, but a solve again rewrites its image.
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})

    @router.post("/{frame_id}/solve", status_code=status.HTTP_202_ACCEPTED)
    async def solve_saved(frame_id: int) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Solve a saved light, for the framing chart; a job of kind ``solve_saved``."""
        with _errors():
            return JobStarted(job=saved().start(frame_id))

    return router


def align_router(polar: Callable[[], PolarAlignmentService]) -> APIRouter:
    router = APIRouter(prefix="/api/align")

    @router.post("/polar", status_code=status.HTTP_202_ACCEPTED)
    async def polar_align(request: PolarAlignRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Polar align from where the mount points (ADR 0034)."""
        options = PolarOptions(
            exposure=request.exposure,
            binning=request.binning,
            step=request.step,
            side=request.side,
            settle=request.settle,
            tolerance=request.tolerance,
            min_altitude=request.min_altitude,
            back=request.back,
        )
        with _errors():
            return JobStarted(job=polar().start(options))

    @router.post("/polar/finish", status_code=status.HTTP_204_NO_CONTENT)
    async def finish() -> Response:  # pyright: ignore[reportUnusedFunction]
        """End the knobs' phase: back to the start and done."""
        with _errors():
            polar().finish()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except SolveError as e:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if e.reason is Failure.UNAVAILABLE
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(code, str(e)) from e
    except (ResourceBusyError, PointingError, FrameUnavailableError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except StorageError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except (CameraNotReadyError, MountNotReadyError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
