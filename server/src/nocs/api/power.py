"""Power outputs, dew heaters and auto-dew (ADR 0017)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import AutoDewRequest, OutputRequest
from nocs.devices import DeviceError
from nocs.jobs import ResourceBusyError
from nocs.power.service import AutoDewError, PowerNotReadyError, PowerService


def power_router(power: Callable[[], PowerService]) -> APIRouter:
    router = APIRouter(prefix="/api/power")

    @router.put("/outputs/{output_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def set_output(output_id: str, request: OutputRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _power_errors():
            await power().set_output(
                output_id,
                on=request.on,
                duty=request.duty,
                voltage=request.voltage,
                force=request.force,
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/auto-dew", status_code=status.HTTP_204_NO_CONTENT)
    async def set_auto_dew(request: AutoDewRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _power_errors():
            await power().set_auto_dew(request.on)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _power_errors() -> Generator[None]:
    try:
        yield
    except (ResourceBusyError, AutoDewError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except PowerNotReadyError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except (DeviceError, ConnectionError) as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
