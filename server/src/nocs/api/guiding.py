"""Guiding with PHD2: connecting its equipment, looping and stopping (ADR 0022, 0023)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from nocs.api.schemas import (
    DitherNowRequest,
    GuideEntryModel,
    GuideRequest,
    GuideSteps,
    GuidingExposureRequest,
    GuidingLoopRequest,
    JobStarted,
)
from nocs.guiding import (
    GuidingNotReadyError,
    GuidingService,
    Phd2ConnectionError,
    Phd2Error,
    Settle,
)
from nocs.jobs import ResourceBusyError


def guiding_router(guiding: Callable[[], GuidingService]) -> APIRouter:
    router = APIRouter(prefix="/api/guiding")

    @router.post("/connect", status_code=status.HTTP_204_NO_CONTENT)
    async def connect() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _guiding_errors():
            await guiding().connect()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
    async def disconnect() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _guiding_errors():
            await guiding().disconnect()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/loop", status_code=status.HTTP_204_NO_CONTENT)
    async def loop(request: GuidingLoopRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _guiding_errors():
            await guiding().loop(request.exposure)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/guide", status_code=status.HTTP_202_ACCEPTED)
    async def guide(request: GuideRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Start guiding; the job ends once PHD2 has settled, and guiding goes on."""
        settle = Settle(request.settle.pixels, request.settle.time, request.settle.timeout)
        with _guiding_errors():
            job = guiding().guide(recalibrate=request.recalibrate, settle=settle)
        return JobStarted(job=job)

    @router.get("/steps")
    async def steps(  # pyright: ignore[reportUnusedFunction]
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=5000)] = 5000,
    ) -> GuideSteps:
        """The guiding run's graph: entries numbered above ``after``, oldest first."""
        service = guiding()
        entries = service.history.after(after, limit)
        return GuideSteps(
            steps=[GuideEntryModel.model_validate(e.to_json()) for e in entries],
            pixel_scale=service.pixel_scale,
        )

    @router.post("/dither", status_code=status.HTTP_202_ACCEPTED)
    async def dither(request: DitherNowRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """Dither now, by up to ``pixels`` of the main camera; the job ends once settled."""
        settle = Settle(request.settle.pixels, request.settle.time, request.settle.timeout)
        with _guiding_errors():
            service = guiding()
            job = service.dither_job(
                service.guide_pixels(request.pixels), settle=settle, ra_only=request.ra_only
            )
        return JobStarted(job=job)

    @router.post("/stop", status_code=status.HTTP_204_NO_CONTENT)
    async def stop() -> Response:  # pyright: ignore[reportUnusedFunction]
        with _guiding_errors():
            await guiding().stop()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/exposure", status_code=status.HTTP_204_NO_CONTENT)
    async def set_exposure(request: GuidingExposureRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _guiding_errors():
            await guiding().set_exposure(request.exposure)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _guiding_errors() -> Generator[None]:
    try:
        yield
    except ResourceBusyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except GuidingNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (Phd2Error, Phd2ConnectionError, TimeoutError) as e:
        # PHD2 failed or refused: an upstream error.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"PHD2: {e}") from e
