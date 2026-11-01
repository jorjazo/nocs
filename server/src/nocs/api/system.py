"""Reboot, power off and rename the box through nocs-system (ADR 0027); diagnostics."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import HostnameRequest, ShutdownRequest
from nocs.services.system import OperationUnavailableError, SystemBusyError, SystemService
from nocs.system.client import HelperUnavailableError
from nocs.system.protocol import HelperError


def system_router(system: Callable[[], SystemService]) -> APIRouter:
    router = APIRouter(prefix="/api/system")

    @router.post("/reboot", status_code=status.HTTP_204_NO_CONTENT)
    async def reboot(request: ShutdownRequest | None = None) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _system_errors():
            await system().reboot(force=request is not None and request.force)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/poweroff", status_code=status.HTTP_204_NO_CONTENT)
    async def power_off(request: ShutdownRequest | None = None) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _system_errors():
            await system().power_off(force=request is not None and request.force)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/services/{service}/restart", status_code=status.HTTP_204_NO_CONTENT)
    async def restart_service(  # pyright: ignore[reportUnusedFunction]
        service: Literal["indiserver", "phd2"], request: ShutdownRequest | None = None
    ) -> Response:
        """Restart indiserver (every device reconnects) or PHD2 (ADR 0030)."""
        with _system_errors():
            await system().restart_service(service, force=request is not None and request.force)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.get("/diagnostics")
    async def diagnostics() -> Response:  # pyright: ignore[reportUnusedFunction]
        """A zip with versions, the state and the last day of the services' logs."""
        name, data = await system().diagnostics()
        headers = {"Content-Disposition": f'attachment; filename="{name}"'}
        return Response(data, media_type="application/zip", headers=headers)

    @router.put("/hostname", status_code=status.HTTP_204_NO_CONTENT)
    async def set_hostname(request: HostnameRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _system_errors():
            await system().set_hostname(request.name)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _system_errors() -> Generator[None]:
    try:
        yield
    except SystemBusyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except (OperationUnavailableError, HelperUnavailableError) as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e
    except HelperError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
