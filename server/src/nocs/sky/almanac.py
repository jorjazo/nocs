"""A night at a site: the Sun's set, rise and twilights, the dark window and the Moon.

A night runs from local noon to the next local noon in local mean solar time
(UTC + longitude / 15 h), like the nights of the frame catalog, and is named after
the date at its start. Rise and set are those of the upper limb on a flat horizon
with refraction (as the almanacs give them; the site's elevation lowers the
pressure, and so the refraction); twilights are the Sun's centre at -6°, -12° and
-18°, geometric. Nights near the poles may lack any of them: the Sun is then below
(or above) a level for the whole night, or never gets there.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import numpy as np

from nocs.devices import Location
from nocs.sky.ephemeris import Floats, Sky, illumination, refraction, sky
from nocs.storage.layout import night_of

STEP = 600.0
"""Seconds between the samples of a night, the charts' resolution."""
type Darkness = Literal["civil", "nautical", "astronomical"]
TWILIGHTS: dict[Darkness, float] = {"civil": -6.0, "nautical": -12.0, "astronomical": -18.0}
"""The Sun's altitude at the end of each twilight."""

_REFINE = 12
"""Bisections of a crossing between samples: STEP / 2**12 ≈ 0.15 s."""


@dataclass(frozen=True)
class Interval:
    start: float
    """Unix seconds."""
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def middle(self) -> float:
        return (self.start + self.end) / 2


@dataclass(frozen=True)
class Moon:
    rise: float | None
    """The first moonrise of the night (upper limb, with refraction), if any."""
    set: float | None
    up: list[Interval]
    """When the Moon is above the horizon during the night."""
    fraction: float
    """Illuminated, at the middle of the dark window (or of the night)."""
    phase: float
    """Degrees then: 0 new, 90 first quarter, 180 full, 270 last quarter."""


@dataclass(frozen=True)
class Night:
    site: Location
    date: date
    span: Interval
    """Local noon to local noon."""
    below_horizon: Interval | None
    """The Sun's upper limb below the horizon: sunset to sunrise, clipped to the span.
    None when the Sun never sets."""
    twilights: dict[Darkness, Interval | None]
    """The Sun below -6°, -12°, -18° (dusk to dawn), clipped to the span."""
    lowest: tuple[float, float]
    """When the Sun is lowest, and its altitude (degrees)."""
    darkness: Darkness | None
    """The darkest twilight the night reaches."""
    moon: Moon
    dark_moonless: list[Interval]
    """The dark window with the Moon below the horizon."""
    sky: Sky
    """The sky every STEP over the chart, from sunset to sunrise (or the whole span)."""

    @property
    def dark(self) -> Interval | None:
        """The darkest window of the night: astronomical darkness, or else nautical..."""
        return self.twilights[self.darkness] if self.darkness is not None else None

    @property
    def sunset(self) -> float | None:
        if self.below_horizon is None or self.below_horizon.start <= self.span.start:
            return None
        return self.below_horizon.start

    @property
    def sunrise(self) -> float | None:
        if self.below_horizon is None or self.below_horizon.end >= self.span.end:
            return None
        return self.below_horizon.end

    def apparent(self, altitude: Floats) -> Floats:
        """Geometric altitudes of the chart made apparent (with refraction)."""
        return altitude + refraction(altitude, self.sky.pressure)


def tonight(site: Location, now: datetime) -> date:
    """The night ``now`` belongs to (it changes at local noon)."""
    return night_of(now, site.longitude)


@functools.lru_cache(maxsize=32)
def night(site: Location, day: date) -> Night:
    """The night that starts on ``day`` at ``site``."""
    noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC) - timedelta(
        hours=site.longitude / 15
    )
    span = Interval(noon.timestamp(), noon.timestamp() + 86400)
    grid = np.arange(
        math.floor(span.start / STEP) * STEP, math.ceil(span.end / STEP) * STEP + 1, STEP
    )
    whole = sky(site, grid)
    p = whole.pressure

    def sun_rise_set(s: Sky) -> Floats:
        return s.sun.alt + s.sun.semidiameter + refraction(s.sun.alt, p)

    def moon_rise_set(s: Sky) -> Floats:
        return s.moon.alt + s.moon.semidiameter + refraction(s.moon.alt, p)

    lowest = _lowest(site, grid, whole.sun.alt)
    below_horizon = _around(_below(site, whole, sun_rise_set, span), lowest[0])
    twilights: dict[Darkness, Interval | None] = {}
    for name, level in TWILIGHTS.items():

        def twilight(s: Sky, level: float = level) -> Floats:
            return s.sun.alt - level

        twilights[name] = _around(_below(site, whole, twilight, span), lowest[0])
    darkness: Darkness | None = None
    for name, interval in twilights.items():  # lighter to darker
        if interval is not None:
            darkness = name
    dark = twilights[darkness] if darkness is not None else None

    moon_down = _below(site, whole, moon_rise_set, span)
    moon_up = _complement(moon_down, span)
    middle = dark.middle if dark is not None else lowest[0]
    at_middle = sky(site, [middle])
    fraction, phase = illumination(at_middle.sun.geocentric, at_middle.moon.geocentric)
    moon = Moon(
        rise=next((i.start for i in moon_up if i.start > span.start), None),
        set=next((i.end for i in moon_up if i.end < span.end), None),
        up=moon_up,
        fraction=float(fraction[0]),
        phase=float(phase[0]),
    )
    dark_moonless = intersect(moon_down, [dark]) if dark is not None else []

    chart = below_horizon if below_horizon is not None else span
    inside = (grid >= chart.start - STEP) & (grid <= chart.end + STEP)
    first, last = int(np.argmax(inside)), len(grid) - int(np.argmax(inside[::-1]))
    return Night(
        site=site,
        date=day,
        span=span,
        below_horizon=below_horizon,
        twilights=twilights,
        lowest=lowest,
        darkness=darkness,
        moon=moon,
        dark_moonless=dark_moonless,
        sky=sky(site, grid[first:last]),
    )


def intervals_above(times: Floats, values: Floats) -> list[Interval]:
    """Where sampled ``values`` are ≥ 0, crossings interpolated linearly."""
    above = values >= 0
    result: list[Interval] = []
    start = float(times[0]) if above[0] else None
    for i in np.nonzero(above[1:] != above[:-1])[0]:
        t0, t1, v0, v1 = times[i], times[i + 1], values[i], values[i + 1]
        t = float(t0 + (t1 - t0) * v0 / (v0 - v1))
        if above[i + 1]:
            start = t
        elif start is not None:
            result.append(Interval(start, t))
            start = None
    if start is not None:
        result.append(Interval(start, float(times[-1])))
    return result


def _below(
    site: Location, whole: Sky, f: Callable[[Sky], Floats], span: Interval
) -> list[Interval]:
    """Where ``f`` of the sky is below zero within the span, crossings refined."""
    values = f(whole)
    grid = whole.times
    negative = values < 0
    index = np.nonzero(negative[1:] != negative[:-1])[0]
    lo, hi = grid[index].copy(), grid[index + 1].copy()
    falling = negative[index + 1]
    for _ in range(_REFINE if len(index) else 0):
        mid = (lo + hi) / 2
        crossed = (f(sky(site, mid)) < 0) == falling
        hi, lo = np.where(crossed, mid, hi), np.where(crossed, lo, mid)
    crossings = (lo + hi) / 2

    result: list[Interval] = []
    start = float(grid[0]) if negative[0] else None
    for t, down in zip(crossings.tolist(), falling.tolist(), strict=True):
        if down:
            start = t
        elif start is not None:
            result.append(Interval(start, t))
            start = None
    if start is not None:
        result.append(Interval(start, float(grid[-1])))
    return intersect(result, [span])


def _around(intervals: list[Interval], when: float) -> Interval | None:
    """The interval containing ``when`` (the Sun's lowest), or else the longest one."""
    for interval in intervals:
        if interval.start <= when <= interval.end:
            return interval
    return max(intervals, key=lambda i: i.duration, default=None)


def _lowest(site: Location, grid: Floats, altitude: Floats) -> tuple[float, float]:
    """The Sun's lowest point: the lowest sample, refined by a parabola through three."""
    i = int(np.clip(np.argmin(altitude), 1, len(grid) - 2))
    y0, y1, y2 = (float(v) for v in altitude[i - 1 : i + 2])
    curvature = y0 - 2 * y1 + y2
    offset = 0.5 * (y0 - y2) / curvature if curvature > 0 else 0.0
    when = float(grid[i]) + float(np.clip(offset, -1, 1)) * STEP
    return when, float(sky(site, [when]).sun.alt[0])


def _complement(intervals: list[Interval], span: Interval) -> list[Interval]:
    result: list[Interval] = []
    start = span.start
    for interval in intervals:
        if interval.start > start:
            result.append(Interval(start, interval.start))
        start = interval.end
    if start < span.end:
        result.append(Interval(start, span.end))
    return result


def intersect(a: list[Interval], b: list[Interval]) -> list[Interval]:
    result: list[Interval] = []
    for x in a:
        for y in b:
            start, end = max(x.start, y.start), min(x.end, y.end)
            if end > start:
                result.append(Interval(start, end))
    return sorted(result, key=lambda i: i.start)
