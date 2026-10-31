"""The target catalog: search and look up deep-sky objects (ADR 0019).

Observers may use it too: the data is public and these endpoints only read.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

import anyio
from fastapi import APIRouter, HTTPException, Query, status

from nocs.api.schemas import CatalogMatch, CatalogObject, CatalogSource
from nocs.targets import Target, TargetCatalog, bundled_catalog, loaded_catalog


def targets_router() -> APIRouter:
    router = APIRouter(prefix="/api/targets")

    @router.get("/search")
    async def search(  # pyright: ignore[reportUnusedFunction]
        q: Annotated[str, Query(min_length=1, max_length=100)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> list[CatalogMatch]:
        matches = (await _catalog()).search(q, limit)
        return [CatalogMatch(object=_object(m.target), matched=m.matched) for m in matches]

    @router.get("/objects/{designation}")
    async def get_object(designation: str) -> CatalogObject:  # pyright: ignore[reportUnusedFunction]
        target = (await _catalog()).get(designation)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no object {designation}")
        return _object(target)

    @router.get("/sources")
    async def sources() -> list[CatalogSource]:  # pyright: ignore[reportUnusedFunction]
        return [CatalogSource(**asdict(s)) for s in (await _catalog()).sources]

    return router


async def _catalog() -> TargetCatalog:
    # Loading takes 0.36 s on the Pi 5 (0.08 s on a laptop): off the event loop, once.
    return loaded_catalog() or await anyio.to_thread.run_sync(bundled_catalog)


def _object(target: Target) -> CatalogObject:
    return CatalogObject(
        id=target.id,
        label=target.label,
        type=target.type,
        ra=target.ra,
        dec=target.dec,
        constellation=target.constellation,
        magnitude=target.magnitude,
        major_axis=target.major_axis,
        minor_axis=target.minor_axis,
        position_angle=target.position_angle,
        aliases=list(target.aliases),
        names=list(target.names),
        names_es=list(target.names_es),
    )
