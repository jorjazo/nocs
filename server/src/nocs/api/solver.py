"""Plate solving commands: solve a frame of the main camera, and sync the mount to it."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import JobStarted, SolveRequest
from nocs.devices import DeviceError
from nocs.imaging import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.mount.service import MountNotReadyError, PointingError
from nocs.pointing import PointingService, SolveOptions
from nocs.solving import Failure, SolveError


def solver_router(pointing: Callable[[], PointingService]) -> APIRouter:
    router = APIRouter(prefix="/api/solver")

    @router.post("/solve", status_code=status.HTTP_202_ACCEPTED)
    async def solve(request: SolveRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
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
    except (ResourceBusyError, PointingError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (CameraNotReadyError, MountNotReadyError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
