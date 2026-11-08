"""Saved sites and the active one (ADR 0038); ``sites`` in the state shows them."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import ActiveSiteRequest, SiteCreated
from nocs.jobs import ResourceBusyError
from nocs.sites import Site, SiteError, SiteService


def sites_router(sites: Callable[[], SiteService]) -> APIRouter:
    router = APIRouter(prefix="/api/sites")

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def add(site: Site) -> SiteCreated:  # pyright: ignore[reportUnusedFunction]
        return SiteCreated(id=sites().add(site))

    @router.put("/active", status_code=status.HTTP_204_NO_CONTENT)
    async def activate(  # pyright: ignore[reportUnusedFunction]
        request: ActiveSiteRequest,
    ) -> Response:
        """Refused while a job holds the mount."""
        with _errors():
            sites().activate(request.id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def put(site_id: str, site: Site) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Change a saved site; the active one is refused while a job holds the mount."""
        with _errors():
            sites().put(site_id, site)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete(site_id: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Forget a site; deleting the active one leaves the box with none."""
        with _errors():
            sites().delete(site_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


@contextlib.contextmanager
def _errors() -> Generator[None]:
    try:
        yield
    except SiteError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except ResourceBusyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"the site cannot change now: {e}") from e
