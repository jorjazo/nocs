"""Measure the framing chart's data: loading the stars, and answering a chart request.

    uv run --project server python dev/catalog/measure_chart.py

A request is what `GET /api/targets/chart` does: stars and objects around a point,
turned into the response's JSON (without HTTP), at the radii the web chart asks for.
"""

from __future__ import annotations

import gc
import statistics
import time

from nocs.api.schemas import SkyChart
from nocs.api.targets import _brightest, _object  # pyright: ignore[reportPrivateUsage]
from nocs.targets import bundled_catalog
from nocs.targets.stars import StarCatalog

# NGC 292 (the SMC), NGC 253, the Milky Way in Crux (densest), the south pole.
CENTRES = [
    ("NGC 292", 0.8768, -72.83),
    ("NGC 253", 0.7928, -25.29),
    ("Crux", 12.5, -60.0),
    ("pole", 0.0, -89.5),
]
# The web chart asks for 1.6 times the view's half diagonal and a magnitude for its span.
REQUESTS = [(1.5, 10.0), (4.0, 10.0), (10.0, 8.6), (30.0, 6.9)]


def rss_kb() -> int:
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


def main() -> None:
    catalog = bundled_catalog()
    gc.collect()
    before = rss_kb()
    started = time.perf_counter()
    stars = StarCatalog.load()
    loaded = time.perf_counter() - started
    print(f"stars: {len(stars)} loaded in {loaded:.3f} s, +{(rss_kb() - before) / 1024:.1f} MB RSS")

    print(f"{'centre':8} {'radius':>6} {'mag':>5} {'stars':>6} {'objects':>7} {'kB':>6} {'ms':>7}")
    for name, ra, dec in CENTRES:
        for radius, magnitude in REQUESTS:
            times: list[float] = []
            body = b""
            count = objects = 0
            for _ in range(20):
                started = time.perf_counter()
                field = stars.near(ra, dec, radius, magnitude, 6000)
                near = _brightest(catalog.near(ra, dec, radius), 300)
                chart = SkyChart(
                    ra=ra,
                    dec=dec,
                    radius=radius,
                    magnitude=magnitude,
                    stars=[
                        [round(r, 6), round(d, 5), round(m, 2)]
                        for r, d, m in zip(
                            field.ra.tolist(),
                            field.dec.tolist(),
                            field.magnitude.tolist(),
                            strict=True,
                        )
                    ],
                    truncated=field.truncated,
                    star_catalog=True,
                    objects=[_object(t) for t in near],
                )
                body = chart.model_dump_json().encode()
                times.append(time.perf_counter() - started)
                count, objects = len(field), len(near)
            print(
                f"{name:8} {radius:6.1f} {magnitude:5.1f} {count:6} {objects:7} "
                f"{len(body) / 1e3:6.0f} {statistics.median(times) * 1e3:7.1f}"
            )


if __name__ == "__main__":
    main()
