"""Tonight's sky at the active profile's site: the almanac and targets' visibility."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Annotated, overload

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Query, status

from nocs.api.schemas import (
    Almanac,
    MoonNight,
    SkyVisibility,
    TargetVisibility,
    TimeInterval,
)
from nocs.clock import Clock
from nocs.devices import Location
from nocs.equipment import Site
from nocs.sky import (
    Floats,
    Interval,
    Night,
    Target,
    horizon_altitude,
    night,
    tonight,
    visibility,
)

MAX_TARGETS = 50

type Resolver = Callable[[str], Target | None]
"""Finds a target by name (e.g. a catalog id), or None if there is none."""


def sky_router(
    site: Callable[[], Site | None],
    clock: Callable[[], Clock],
    resolve: Resolver | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/sky")

    async def night_at(day: date | None) -> tuple[Site, Night]:
        where = site()
        if where is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "the active profile has no site: set it in the profile"
            )
        location = Location(where.latitude, where.longitude, where.elevation)
        day = day or tonight(location, clock().now())
        return where, await anyio.to_thread.run_sync(night, location, day)

    @router.get("/tonight")
    async def almanac(  # pyright: ignore[reportUnusedFunction]
        date: Annotated[date | None, Query(description="The night's first date.")] = None,
    ) -> Almanac:
        where, n = await night_at(_checked(date))
        moon = n.sky.moon
        return Almanac(
            night=n.date.isoformat(),
            site=where,
            start=_iso(n.span.start),
            end=_iso(n.span.end),
            sunset=_iso(n.sunset),
            sunrise=_iso(n.sunrise),
            civil=_interval(n.twilights["civil"]),
            nautical=_interval(n.twilights["nautical"]),
            astronomical=_interval(n.twilights["astronomical"]),
            darkness=n.darkness,
            dark=_interval(n.dark),
            dark_moonless=[_span(i) for i in n.dark_moonless],
            sun_lowest=_iso(n.lowest[0]),
            sun_lowest_altitude=round(n.lowest[1], 2),
            times=[_iso(float(t)) for t in n.sky.times],
            sun_altitude=_rounded(n.sky.sun.alt),
            moon=MoonNight(
                rise=_iso(n.moon.rise),
                set=_iso(n.moon.set),
                up=[_span(i) for i in n.moon.up],
                fraction=round(n.moon.fraction, 3),
                phase=round(n.moon.phase, 1),
                altitude=_rounded(n.apparent(moon.alt)),
                azimuth=_rounded(moon.az),
            ),
        )

    @router.get("/visibility")
    async def target_visibility(  # pyright: ignore[reportUnusedFunction]
        target: Annotated[
            list[str],
            Query(
                min_length=1,
                max_length=MAX_TARGETS,
                description='"RA,Dec": J2000 hours and degrees, e.g. "0.88,-72.8".',
            ),
        ],
        date: Annotated[date | None, Query(description="The night's first date.")] = None,
        min_altitude: Annotated[float, Query(ge=-10, le=90)] = 30.0,
    ) -> SkyVisibility:
        targets = [_target(t, resolve) for t in target]
        where, n = await night_at(_checked(date))
        results = await anyio.to_thread.run_sync(
            lambda: visibility(n, targets, min_altitude=min_altitude, horizon=where.horizon)
        )
        return SkyVisibility(
            night=n.date.isoformat(),
            min_altitude=min_altitude,
            darkness=n.darkness,
            dark=_interval(n.dark),
            times=[_iso(float(t)) for t in n.sky.times],
            targets=[
                TargetVisibility(
                    target=name,
                    ra=t.ra,
                    dec=t.dec,
                    altitude=_rounded(v.altitude),
                    azimuth=_rounded(v.azimuth),
                    horizon=_rounded(horizon_altitude(where.horizon, v.azimuth)),
                    transit=_iso(v.transit),
                    transit_altitude=round(v.transit_altitude, 2),
                    above_minimum=round(v.above_minimum),
                    above_horizon=round(v.above_horizon),
                    windows=[_span(w) for w in v.windows],
                    best=_interval(v.best),
                    observable=round(v.observable),
                    moon_separation=round(v.moon_separation, 1),
                    moon_separation_min=None
                    if v.moon_separation_min is None
                    else round(v.moon_separation_min, 1),
                )
                for name, t, v in zip(target, targets, results, strict=True)
            ],
        )

    return router


def _target(text: str, resolve: Resolver | None) -> Target:
    """``"RA,Dec"``, or a name the resolver knows."""
    parts = text.split(",")
    if len(parts) == 2:
        try:
            ra, dec = float(parts[0]), float(parts[1])
        except ValueError:
            pass
        else:
            if not (0 <= ra < 24 and -90 <= dec <= 90):
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{text!r}: RA is 0..24 h and Dec -90..90°",
                )
            return Target(ra, dec)
    found = resolve(text) if resolve is not None else None
    if found is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{text!r} is not RA,Dec (J2000 hours and degrees)"
            + (" nor a known object" if resolve is not None else ""),
        )
    return found


def _checked(day: date | None) -> date | None:
    """ERFA's leap seconds and models are good for these years."""
    if day is not None and not 1960 <= day.year <= 2100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the date is out of range")
    return day


@overload
def _iso(t: float) -> str: ...
@overload
def _iso(t: float | None) -> str | None: ...
def _iso(t: float | None) -> str | None:
    if t is None:
        return None
    return datetime.fromtimestamp(round(t), UTC).isoformat(timespec="seconds")


def _span(i: Interval) -> TimeInterval:
    return TimeInterval(start=_iso(i.start), end=_iso(i.end))


def _interval(i: Interval | None) -> TimeInterval | None:
    return _span(i) if i is not None else None


def _rounded(values: Floats) -> list[float]:
    return [round(v, 1) for v in values.tolist()]
