"""Measure the bundled target catalog: load time, memory and search latency.

    PYTHONPATH=server/src python3 dev/catalog/measure.py

Needs only Python 3.12+ and its standard library: it runs without nocsd's environment.
"""

from __future__ import annotations

import gc
import statistics
import time
from importlib import resources

from nocs.targets import TargetCatalog
from nocs.targets.catalog import DATA_FILE

QUERIES = [
    "m31",
    "M 42",
    "ngc292",
    "NGC 0292",
    "NGC 253",
    "smc",
    "sculptor galaxy",
    "nebulosa de orion",
    "pequeña nube",
    "c65",
    "ngc 2",
    "m",
    "galaxy",
    "nebula",
    "no such thing",
]


def rss_kb() -> int:
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    raise RuntimeError("no VmRSS")


def main() -> None:
    size = len(resources.files("nocs.targets").joinpath("data", DATA_FILE).read_bytes())
    gc.collect()
    before = rss_kb()
    start = time.perf_counter()
    catalog = TargetCatalog.load()
    load = time.perf_counter() - start
    gc.collect()
    memory = rss_kb() - before

    loads: list[float] = []
    for _ in range(3):
        start = time.perf_counter()
        TargetCatalog.load()
        loads.append(time.perf_counter() - start)

    times: dict[str, float] = {}
    for query in QUERIES:
        runs: list[float] = []
        for _ in range(50):
            start = time.perf_counter()
            catalog.search(query)
            runs.append(time.perf_counter() - start)
        times[query] = statistics.median(runs)

    print(f"objects: {len(catalog.targets)}, file: {size / 1e3:.0f} kB")
    print(f"load: first {load * 1e3:.0f} ms, then {min(loads) * 1e3:.0f} ms")
    print(f"memory: RSS +{memory / 1e3:.1f} MB")
    for query, seconds in times.items():
        print(f"  {query!r:22} {seconds * 1e3:6.2f} ms")
    print(
        f"search: median {statistics.median(times.values()) * 1e3:.2f} ms, "
        f"worst {max(times.values()) * 1e3:.2f} ms"
    )


if __name__ == "__main__":
    main()
