"""The Sun and Moon finder (ADR 0049)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

from fastapi import APIRouter, HTTPException, status

from nocs.api.mount import stop_guiding_first
from nocs.api.schemas import FinderRequest, JobStarted
from nocs.devices import DeviceError
from nocs.finder import Body, FinderError, FinderOptions, FinderService
from nocs.guiding import GuidingNotReadyError, GuidingService, Phd2Error
from nocs.imaging import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.mount.service import MountNotReadyError, PointingError


def finder_router(
    finder: Callable[[], FinderService], guiding: Callable[[], GuidingService]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/finder", status_code=status.HTTP_202_ACCEPTED)
    async def find(request: FinderRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Find the Sun or the Moon by its brightness and centre it in the main camera."""
        body = Body(request.body)
        options = FinderOptions(
            body,
            radius=request.radius,
            exposure=request.exposure,
            binning=request.binning,
            tolerance=request.tolerance,
            here=request.here,
            sync=request.sync,
            track=request.track,
        )
        with _errors():
            # Refused before PHD2 stops, not after: the Sun's warning, a body that is down.
            finder().check(options)
        if body is Body.SUN:
            await _stop_phd2(guiding())
        else:
            await stop_guiding_first(guiding(), request.stop_guiding)
        with _errors():
            return JobStarted(job=finder().start(options))

    return router


async def _stop_phd2(guiding: GuidingService) -> None:
    """PHD2's guide camera must not look at the Sun: stop its looping or guiding."""
    if guiding.phd2 is None:
        return
    try:
        await guiding.stop()
    except GuidingNotReadyError:
        return
    except (Phd2Error, TimeoutError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"PHD2: {e}") from e


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except (ResourceBusyError, PointingError, FinderError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (CameraNotReadyError, MountNotReadyError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
