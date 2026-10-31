"""Focuser and filter wheel commands."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import (
    FilterNamesRequest,
    FilterSelectRequest,
    FocuserMoveRequest,
    JobStarted,
)
from nocs.devices import DeviceError
from nocs.filters.service import FilterWheelNotReadyError, FilterWheelService
from nocs.focus.service import FocuserNotReadyError, FocuserService
from nocs.jobs import ResourceBusyError


def accessories_router(
    focuser: Callable[[], FocuserService], filter_wheel: Callable[[], FilterWheelService]
) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.post("/focuser/move", status_code=status.HTTP_202_ACCEPTED)
    async def move(request: FocuserMoveRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            if request.position is not None:
                return JobStarted(job=focuser().move_to(request.position))
            assert request.steps is not None
            return JobStarted(job=focuser().move_by(request.steps))

    @router.post("/focuser/abort", status_code=status.HTTP_202_ACCEPTED)
    async def abort() -> None:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            await focuser().abort()

    @router.post("/filter-wheel/select", status_code=status.HTTP_202_ACCEPTED)
    async def select(request: FilterSelectRequest) -> JobStarted:  # pyright: ignore[reportUnusedFunction]
        wanted = request.filter if request.filter is not None else request.slot
        assert wanted is not None
        with _errors():
            return JobStarted(job=filter_wheel().select(wanted))

    @router.put("/filter-wheel/names", status_code=status.HTTP_204_NO_CONTENT)
    async def names(request: FilterNamesRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _errors():
            await filter_wheel().set_names(request.filters, request.label)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _errors() -> Generator[None]:
    """Map failures of focuser and filter wheel commands to HTTP errors."""
    try:
        yield
    except ResourceBusyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (FocuserNotReadyError, FilterWheelNotReadyError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
