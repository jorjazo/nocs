"""Reboot, power off, rename and network the box through nocs-system (ADR 0027,
ADR 0028), share its frames (ADR 0037); diagnostics."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import (
    AccessPointRequest,
    HostnameRequest,
    NetworkForgetRequest,
    NetworkJoinRequest,
    NetworkModeRequest,
    NetworkSetupRequest,
    ShareRequest,
    ShutdownRequest,
)
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

    # -- updates (ADR 0025) -----------------------------------------------------

    @router.post("/updates/{task}", status_code=status.HTTP_202_ACCEPTED)
    async def update(  # pyright: ignore[reportUnusedFunction]
        task: Literal["check", "install", "rollback"], request: ShutdownRequest | None = None
    ) -> Response:
        """Check, install (nocsd restarts at the end) or go back to the previous NOCS."""
        with _system_errors():
            await system().update(task, force=request is not None and request.force)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    # -- network (ADR 0028) -----------------------------------------------------

    @router.post("/network/join", status_code=status.HTTP_202_ACCEPTED)
    async def network_join(request: NetworkJoinRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        args: dict[str, object] = {"ssid": request.ssid}
        if request.password is not None:
            args["password"] = request.password
        with _system_errors():
            await system().network("network.join", args)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    @router.post("/network/setup", status_code=status.HTTP_202_ACCEPTED)
    async def network_setup(request: NetworkSetupRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        """The first run: country and password of the access point, then maybe a network."""
        with _system_errors():
            await system().network(
                "network.access_point",
                {"country": request.country.upper(), "password": request.password},
            )
            if request.join is not None:
                args: dict[str, object] = {"ssid": request.join.ssid}
                if request.join.password is not None:
                    args["password"] = request.join.password
                await system().network("network.join", args)
        return Response(status_code=status.HTTP_202_ACCEPTED)

    @router.post("/network/forget", status_code=status.HTTP_204_NO_CONTENT)
    async def network_forget(request: NetworkForgetRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _system_errors():
            await system().network("network.forget", {"ssid": request.ssid})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/network/access-point", status_code=status.HTTP_204_NO_CONTENT)
    async def network_access_point(request: AccessPointRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        args = {k: v for k, v in request.model_dump().items() if v is not None}
        if not args:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "nothing to change")
        with _system_errors():
            await system().network("network.access_point", args)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/network/mode", status_code=status.HTTP_204_NO_CONTENT)
    async def network_mode(request: NetworkModeRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        with _system_errors():
            await system().network("network.mode", {"pin": request.pin})
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # -- SMB share (ADR 0037) ----------------------------------------------------

    @router.put("/share", status_code=status.HTTP_204_NO_CONTENT)
    async def share(request: ShareRequest) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Switch the read-only SMB share of the frames on or off."""
        with _system_errors():
            await system().share(request.on)
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
