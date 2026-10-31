"""Measure tonight's sky: the almanac of a night and the visibility of targets.

uv run --project server python dev/sky/measure.py
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from datetime import date, timedelta

import numpy as np

from nocs.devices import Location
from nocs.equipment import HorizonPoint
from nocs.sky import Target, night, visibility

SITE = Location(-30.03, -70.67, 700)
HILL = [
    HorizonPoint(azimuth=0, altitude=30),
    HorizonPoint(azimuth=60, altitude=10),
    HorizonPoint(azimuth=300, altitude=10),
]
NIGHTS = 20


def timed(fn: Callable[[], object], runs: int) -> list[float]:
    result: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        result.append((time.perf_counter() - start) * 1000)
    return result


def summary(label: str, ms: list[float]) -> None:
    print(f"{label:<34} median {statistics.median(ms):7.1f} ms  max {max(ms):7.1f} ms")


def main() -> None:
    start = time.perf_counter()
    night(SITE, date(2026, 1, 1))
    print(f"first night (imports warm, ERFA cold) {(time.perf_counter() - start) * 1000:.1f} ms")

    days = [date(2026, 11, 15) + timedelta(days=i) for i in range(NIGHTS)]
    almanac: list[float] = []
    for day in days:
        start = time.perf_counter()
        night(SITE, day)  # not cached yet: a new date each time
        almanac.append((time.perf_counter() - start) * 1000)
    summary("almanac (a new night)", almanac)
    summary("almanac (cached)", timed(lambda: night(SITE, days[0]), 100))

    rng = np.random.default_rng(1)
    n = night(SITE, days[0])
    for count in (1, 10, 50):
        targets = [
            Target(float(ra), float(dec))
            for ra, dec in zip(rng.uniform(0, 24, count), rng.uniform(-90, 60, count), strict=True)
        ]
        summary(
            f"visibility, {count} target(s)",
            timed(lambda t=targets: visibility(n, t, horizon=HILL), 20),
        )


if __name__ == "__main__":
    main()
