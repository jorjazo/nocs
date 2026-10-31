"""The target catalog: search and look up deep-sky objects (ADR 0019).

Observers may use it too: the data is public and these endpoints only read.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

import anyio
from fastapi import APIRouter, HTTPException, Query, status

from nocs.api.schemas import CatalogMatch, CatalogObject, CatalogSource, SkyChart
from nocs.targets import Target, TargetCatalog, bundled_catalog, loaded_catalog
from nocs.targets.stars import StarCatalog, bundled_stars, loaded_stars


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
        found = [*(await _catalog()).sources, *(await _stars()).sources]
        return [CatalogSource(**asdict(s)) for s in found]

    @router.get("/chart")
    async def chart(  # pyright: ignore[reportUnusedFunction]
        ra: Annotated[float, Query(ge=0, lt=24, description="J2000, hours.")],
        dec: Annotated[float, Query(ge=-90, le=90, description="J2000, degrees.")],
        radius: Annotated[float, Query(gt=0, le=30, description="Degrees.")],
        magnitude: Annotated[float, Query(le=20)] = 99,
        limit: Annotated[int, Query(ge=1, le=20000, description="Most stars to send.")] = 5000,
        objects: Annotated[int, Query(ge=0, le=2000, description="Most objects to send.")] = 300,
    ) -> SkyChart:
        catalog, stars = await _catalog(), await _stars()
        field = stars.near(ra, dec, radius, magnitude, limit)
        return SkyChart(
            ra=ra,
            dec=dec,
            radius=radius,
            magnitude=min(magnitude, stars.magnitude_limit),
            # Rounded to ~0.05″ and 0.01 mag: the JSON is a third shorter.
            stars=[
                [round(r, 6), round(d, 5), round(m, 2)]
                for r, d, m in zip(
                    field.ra.tolist(), field.dec.tolist(), field.magnitude.tolist(), strict=True
                )
            ],
            truncated=field.truncated,
            star_catalog=len(stars) > 0,
            # A wide view near the Magellanic Clouds holds a thousand: the brightest.
            objects=[_object(t) for t in _brightest(catalog.near(ra, dec, radius), objects)],
        )

    return router


async def _catalog() -> TargetCatalog:
    # Loading takes 0.36 s on the Pi 5 (0.08 s on a laptop): off the event loop, once.
    return loaded_catalog() or await anyio.to_thread.run_sync(bundled_catalog)


def _brightest(targets: list[Target], limit: int) -> list[Target]:
    def order(target: Target) -> float:
        return 99.0 if target.magnitude is None else target.magnitude

    return sorted(targets, key=order)[:limit]


async def _stars() -> StarCatalog:
    return loaded_stars() or await anyio.to_thread.run_sync(bundled_stars)


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
