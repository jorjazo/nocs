"""Saved sites and the active one (ADR 0038); ``sites`` in the state shows them."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Generator

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Response, status

from nocs.api.schemas import ActiveSiteRequest, MapsLink, MapsLinkRequest, SiteCreated
from nocs.jobs import ResourceBusyError
from nocs.sites import Site, SiteError, SiteService, known_zones
from nocs.sites.links import LinkError, LinkUnreachableError, expand, is_short_link


def sites_router(sites: Callable[[], SiteService]) -> APIRouter:
    router = APIRouter(prefix="/api/sites")

    @router.get("/zones")
    async def zones() -> list[str]:  # pyright: ignore[reportUnusedFunction]
        """The time zones a site may name, sorted (the system's list reads files)."""
        return sorted(await anyio.to_thread.run_sync(known_zones))

    @router.post("/maps-link")
    async def maps_link(request: MapsLinkRequest) -> MapsLink:  # pyright: ignore[reportUnusedFunction]
        """Expand a Google Maps short link, which the browser cannot follow itself.

        400 for anything but a short link; 422 when it leads nowhere (a dead link);
        502 when Google cannot be reached (no internet).
        """
        if not is_short_link(request.url):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a Google Maps short link")
        try:
            return MapsLink(url=await expand(request.url))
        except LinkUnreachableError as e:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
        except LinkError as e:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from e

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
