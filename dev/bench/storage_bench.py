#!/usr/bin/env python3
"""Storage benchmark for NOCS frames: microSD vs a USB drive (stdlib only).

What a night does to storage:
  frames   write a 26 MP frame (52.2 MB) and fsync it, N times in a row
  read     read those frames back with a cold page cache (re-solving, downloads)
  small    4 KiB append + fsync, the catalog's and the log's kind of write
  contend  the same small writes on --small-dir while frames stream to --frames-dir

Each test prints one JSON line; dropping the page cache needs `sudo -n`. The run in
docs/spikes/pi5-performance.md, with the drive mounted at /mnt/usb:

    SD=~/storage-bench USB=/mnt/usb/storage-bench B="python3 -I dev/bench/storage_bench.py"
    $B frames $SD/frames; $B read $SD/frames
    $B frames $USB/frames; $B read $USB/frames
    $B small $SD/small; $B small $USB/small
    $B contend --small-dir $SD/small --frames-dir $SD/contend
    $B contend --small-dir $SD/small --frames-dir $USB/contend
    rm -rf $SD $USB
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

FRAME = 6248 * 4176 * 2 + 2880 * 4  # 16-bit pixels plus a FITS header
CHUNK = 4 << 20
BLOCK = os.urandom(CHUNK)


def stats(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)

    def pct(p: float) -> float:
        return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]

    return {
        "n": len(ordered),
        "p50": statistics.median(ordered),
        "p95": pct(95),
        "p99": pct(99),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def write_frame(path: Path) -> float:
    start = time.perf_counter()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        left = FRAME
        while left:
            left -= os.write(fd, BLOCK[: min(left, CHUNK)])
        os.fsync(fd)
    finally:
        os.close(fd)
    return time.perf_counter() - start


def drop_caches() -> None:
    os.sync()
    subprocess.run(["sudo", "-n", "sysctl", "-q", "vm.drop_caches=3"], check=True)


def frames(directory: Path, count: int) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    times = [write_frame(directory / f"frame-{i:03d}.fits") for i in range(count)]
    return {
        "test": "frames",
        "dir": str(directory),
        "seconds": stats(times),
        "mb_per_s": FRAME * count / sum(times) / 1e6,
    }


def read(directory: Path) -> dict[str, object]:
    files = sorted(directory.glob("frame-*.fits"))
    drop_caches()
    times: list[float] = []
    total = 0
    for path in files:
        start = time.perf_counter()
        with open(path, "rb", buffering=0) as f:
            while chunk := f.read(CHUNK):
                total += len(chunk)
        times.append(time.perf_counter() - start)
    return {
        "test": "read",
        "dir": str(directory),
        "seconds": stats(times),
        "mb_per_s": total / sum(times) / 1e6,
    }


def small_writes(directory: Path, count: int) -> list[float]:
    directory.mkdir(parents=True, exist_ok=True)
    data = os.urandom(4096)
    times: list[float] = []
    fd = os.open(directory / "small.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        for _ in range(count):
            start = time.perf_counter()
            os.write(fd, data)
            os.fsync(fd)
            times.append(time.perf_counter() - start)
            time.sleep(0.02)  # a write every ~20 ms, not a tight loop
    finally:
        os.close(fd)
    return times


def ms(values: dict[str, float]) -> dict[str, float]:
    return {k: (v if k == "n" else round(v * 1000, 2)) for k, v in values.items()}


def contend(small_dir: Path, frames_dir: Path, count: int) -> dict[str, object]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    written: list[float] = []

    def stream() -> None:
        i = 0
        while not stop.is_set():
            written.append(write_frame(frames_dir / f"contend-{i % 10:03d}.fits"))
            i += 1

    writer = threading.Thread(target=stream, daemon=True)
    writer.start()
    time.sleep(1)  # let the stream get going
    times = small_writes(small_dir, count)
    stop.set()
    writer.join()
    return {
        "test": "contend",
        "small_dir": str(small_dir),
        "frames_dir": str(frames_dir),
        "small_ms": ms(stats(times)),
        "frames_written": len(written),
        "frame_seconds": stats(written),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("test", choices=["frames", "read", "small", "contend"])
    parser.add_argument("dir", nargs="?", type=Path)
    parser.add_argument("--count", type=int)
    parser.add_argument("--small-dir", type=Path)
    parser.add_argument("--frames-dir", type=Path)
    args = parser.parse_args()
    if args.test == "frames":
        result = frames(args.dir, args.count or 20)
    elif args.test == "read":
        result = read(args.dir)
    elif args.test == "small":
        times = small_writes(args.dir, args.count or 300)
        result = {"test": "small", "dir": str(args.dir), "ms": ms(stats(times))}
    else:
        result = contend(args.small_dir, args.frames_dir, args.count or 300)
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    sys.exit(main())
