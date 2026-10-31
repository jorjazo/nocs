"""When targets are worth imaging during a night: altitude curves, transit, windows.

Altitudes here are apparent (with refraction), as a horizon is measured. The
windows count only the night's darkest window (``Night.dark``), and a target is
observable when it is above both a minimum altitude and the site's horizon profile.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from nocs.equipment import HorizonPoint
from nocs.sky.almanac import Interval, Night, intersect, intervals_above
from nocs.sky.ephemeris import SIDEREAL_DAY, Floats, separation, sky


@dataclass(frozen=True)
class Target:
    ra: float
    """J2000 hours."""
    dec: float
    """J2000 degrees."""


@dataclass(frozen=True)
class Visibility:
    altitude: Floats
    """Apparent, degrees, at each instant of the night's chart."""
    azimuth: Floats
    transit: float
    """The upper culmination closest to the middle of the night (Unix seconds)."""
    transit_altitude: float
    above_minimum: float
    """Seconds of the dark window above the minimum altitude."""
    above_horizon: float
    """Seconds of the dark window above the horizon profile."""
    windows: list[Interval]
    """Within the dark window, above both."""
    moon_separation: float
    """Degrees, at the middle of the best window (or else at transit)."""
    moon_separation_min: float | None
    """Over the dark window."""

    @property
    def best(self) -> Interval | None:
        return max(self.windows, key=lambda w: w.duration, default=None)

    @property
    def observable(self) -> float:
        return sum(w.duration for w in self.windows)


def horizon_altitude(horizon: list[HorizonPoint] | None, azimuth: Floats) -> Floats:
    """The horizon profile's altitude at each azimuth: 0° without a profile."""
    if not horizon:
        return np.zeros_like(azimuth)
    return np.interp(
        azimuth,
        [p.azimuth for p in horizon],
        [p.altitude for p in horizon],
        period=360,
    )


def visibility(
    night: Night,
    targets: list[Target],
    *,
    min_altitude: float = 30.0,
    horizon: list[HorizonPoint] | None = None,
) -> list[Visibility]:
    if not targets:
        return []
    ra = np.array([[t.ra] for t in targets])
    dec = np.array([[t.dec] for t in targets])
    chart = night.sky
    position = chart.star(ra, dec)
    altitude = night.apparent(position.alt)
    limit = horizon_altitude(horizon, position.az)
    moon_distance = separation(position, chart.moon)

    # Transit: from the hour angle at the middle of the night, then once more.
    middle = night.dark.middle if night.dark is not None else night.lowest[0]
    when = np.full(len(targets), middle)
    for _ in range(2):
        at = sky(night.site, when)
        when = when - at.hour_angle(ra[:, 0], dec[:, 0]) / (2 * math.pi) * SIDEREAL_DAY
    at = sky(night.site, when)
    transit_altitude = night.apparent(at.star(ra[:, 0], dec[:, 0]).alt)

    dark = [night.dark] if night.dark is not None else []
    times = chart.times
    in_dark = np.zeros(len(times), dtype=bool)
    for d in dark:
        in_dark |= (times >= d.start) & (times <= d.end)
    windows: list[list[Interval]] = []
    above: list[tuple[float, float]] = []
    for i in range(len(targets)):
        windows.append(
            intersect(
                intervals_above(times, altitude[i] - np.maximum(limit[i], min_altitude)), dark
            )
        )
        above.append(
            (
                _total(intersect(intervals_above(times, altitude[i] - min_altitude), dark)),
                _total(intersect(intervals_above(times, altitude[i] - limit[i]), dark)),
            )
        )
    reference = np.array(
        [
            max(w, key=lambda x: x.duration).middle if w else float(t)
            for w, t in zip(windows, when, strict=True)
        ]
    )
    at = sky(night.site, reference)
    moon_reference = separation(at.star(ra[:, 0], dec[:, 0]), at.moon)
    return [
        Visibility(
            altitude=altitude[i],
            azimuth=position.az[i],
            transit=float(when[i]),
            transit_altitude=float(transit_altitude[i]),
            above_minimum=above[i][0],
            above_horizon=above[i][1],
            windows=windows[i],
            moon_separation=float(moon_reference[i]),
            moon_separation_min=float(moon_distance[i][in_dark].min()) if in_dark.any() else None,
        )
        for i in range(len(targets))
    ]


def _total(intervals: list[Interval]) -> float:
    return sum(i.duration for i in intervals)
