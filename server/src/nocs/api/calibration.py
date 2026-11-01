"""Calibration frames: the library for a night or a planned sequence (ADR 0036)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import Annotated

import anyio
from fastapi import APIRouter, HTTPException, Query, status

from nocs.api.schemas import (
    CalibrationGroup,
    CalibrationMatch,
    CalibrationNeed,
    CalibrationReport,
    CalibrationSequence,
    CalibrationSequenceRequest,
    CalibrationSetup,
    FlatWindows,
    JobStarted,
    TwilightWindow,
)
from nocs.calibration.darks import SEQUENCE_ID, frames
from nocs.calibration.flats import FlatPlan, FlatsError, FlatsService
from nocs.calibration.library import Match, Need, Report, Setup, Wanted
from nocs.calibration.service import CalibrationError, CalibrationService
from nocs.imaging import CameraNotReadyError
from nocs.jobs import ResourceBusyError
from nocs.storage import StorageError

type Count = Annotated[int, Query(ge=0, le=500)]


def calibration_router(
    calibration: Callable[[], CalibrationService], flats: Callable[[], FlatsService]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/flats/window")
    async def flat_windows() -> FlatWindows:  # pyright: ignore[reportUnusedFunction]
        """When the twilight sky makes flats, at the profile's site."""
        try:
            sun, found = await anyio.to_thread.run_sync(flats().windows)
        except FlatsError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        return FlatWindows(
            sun=round(sun, 2),
            windows=[
                TwilightWindow(
                    phase=w.phase,
                    start=w.start.isoformat(timespec="seconds"),
                    end=w.end.isoformat(timespec="seconds"),
                )
                for w in found
            ],
        )

    @router.post("/flats", status_code=status.HTTP_202_ACCEPTED)
    async def take_flats(plan: FlatPlan) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        """The flats wizard: each filter's exposure found, then its flats (ADR 0036)."""
        try:
            return JobStarted(job=flats().start(plan))
        except ResourceBusyError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
        except CameraNotReadyError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e

    @router.get("/calibration")
    async def library(  # pyright: ignore[reportUnusedFunction]
        night: int | None = None,
        sequence: str | None = None,
        darks: Count = 20,
        bias: Count = 50,
        flats: Count = 20,
    ) -> CalibrationReport:
        """What matches a night's lights (``night``) or a sequence's planned ones, and what
        is missing for the wanted counts."""
        if (night is None) == (sequence is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "give a night or a sequence")
        wanted = Wanted(darks, bias, flats)
        service = calibration()
        with _errors():
            if night is not None:
                row, found = await anyio.to_thread.run_sync(service.for_night, night, wanted)
                return wire(found, row.night)
            assert sequence is not None
            found = await anyio.to_thread.run_sync(service.for_sequence, sequence, wanted)
            return wire(found, None)

    @router.post("/calibration/sequence")
    async def darks(request: CalibrationSequenceRequest) -> CalibrationSequence:  # pyright: ignore[reportUnusedFunction]
        """Keep the missing darks and bias as the ``calibration`` sequence (not started)."""
        if (request.night is None) == (request.sequence is None):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "give a night or a sequence")
        wanted = Wanted(request.darks, request.bias, 0)
        service = calibration()
        with _errors():
            built, left = await anyio.to_thread.run_sync(
                service.darks, request.night, request.sequence, wanted, request.warm
            )
        return CalibrationSequence(
            id=SEQUENCE_ID, frames=frames(built), left_out=[_need(n) for n in left]
        )

    return router


def _need(n: Need) -> CalibrationNeed:
    return CalibrationNeed(
        kind=n.kind,
        setup=_setup(n.setup),
        count=n.count,
        exposure=n.exposure,
        temperature=n.temperature,
        filter=n.filter,
    )


def wire(report: Report, night: str | None) -> CalibrationReport:
    return CalibrationReport(
        night=night,
        groups=[
            CalibrationGroup(
                setup=_setup(g.setup),
                filter=g.filter,
                exposure=g.exposure,
                temperature=g.temperature,
                lights=g.lights,
                focus=g.focus,
                darks=_match(g.darks),
                flats=_match(g.flats),
                bias=_match(g.bias),
                flat_calibration=_match(g.flat_calibration),
            )
            for g in report.groups
        ],
        needs=[_need(n) for n in report.needs],
        frames=len(report.frames),
    )


def _setup(setup: Setup) -> CalibrationSetup:
    return CalibrationSetup(
        camera=setup.camera,
        width=setup.width,
        height=setup.height,
        binning=setup.binning,
        gain=setup.gain,
        offset=setup.offset,
    )


def _match(match: Match) -> CalibrationMatch:
    return CalibrationMatch(
        frames=len(match.frames),
        nights=sorted(match.nights, reverse=True),
        temperature=match.temperature,
    )


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no night or sequence {e}") from e
    except CalibrationError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except StorageError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
