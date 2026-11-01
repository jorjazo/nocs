"""Benchmark live stacking's per-frame cost in the imaging worker (ADR 0037).

Runs nocsd's own code (``nocs.stacking.stack.add_frame``, then the preview pipeline
for comparison) on a series of full-size frames, as the worker would see them one
after another, and prints the median time of every step, the worker's peak memory
and the stack's own size.

Frames are synthetic by default: a 26 MP RGGB field like the reference rig's
(6248x4176), with dithers of a few pixels and a meridian flip (180 degrees) half
way. ``--frames DIR`` stacks the FITS files of a directory instead, in name order
(the bench's simulator samples, or a night's lights of one target).

Usage (from the repository root):

    uv run --project server python dev/bench/stack_bench.py [--count 12] [--json out.json]
    uv run --project server python dev/bench/stack_bench.py --frames dev/bench/samples
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import platform
import resource
import statistics
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]

from nocs.imaging import pipeline
from nocs.stacking import stack
from nocs.stacking.register import Transform

_fits: Any = fits

WIDTH, HEIGHT = 6248, 4176
STARS = 4000
STEPS = ("load", "reduce", "stars", "register", "warp", "accumulate", "render")


def synthetic(directory: Path, count: int, seed: int = 1) -> list[Path]:
    """``count`` 26 MP RGGB frames of one field: dithers, and a flip half way."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-300, WIDTH + 300, STARS)
    y = rng.uniform(-300, HEIGHT + 300, STARS)
    flux = 4e3 * (1 - rng.uniform(0, 0.97, STARS)) ** -1.5
    colour = rng.dirichlet((6.0, 8.0, 5.0), STARS)
    masks = np.zeros((3, HEIGHT, WIDTH), dtype=np.float32)  # R, G, B positions
    masks[0, 0::2, 0::2] = 1
    masks[1, 0::2, 1::2] = 1
    masks[1, 1::2, 0::2] = 1
    masks[2, 1::2, 1::2] = 1
    paths: list[Path] = []
    for i in range(count):
        dither = (rng.uniform(-15, 15), rng.uniform(-15, 15))
        move = Transform.of(0.0, dither)
        if i >= count // 2:
            move = Transform.of(180.0, (WIDTH + dither[0], HEIGHT + dither[1]))
        m = np.vstack((move.matrix(), (0, 0, 1)))
        inverse = np.linalg.inv(m)
        fx = np.asarray(inverse[0, 0] * x + inverse[0, 1] * y + inverse[0, 2], dtype=np.float64)
        fy = np.asarray(inverse[1, 0] * x + inverse[1, 1] * y + inverse[1, 2], dtype=np.float64)
        inside = (fx >= 0) & (fx < WIDTH - 1) & (fy >= 0) & (fy < HEIGHT - 1)
        signal = np.full((HEIGHT, WIDTH), 0.0, dtype=np.float32)
        for channel in range(3):
            impulses = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
            np.add.at(
                impulses,
                (np.round(fy[inside]).astype(int), np.round(fx[inside]).astype(int)),
                (flux * colour[:, channel])[inside].astype(np.float32),
            )
            blurred = cv2.GaussianBlur(impulses, (0, 0), 2.6)
            signal += blurred * masks[channel] * (4 / 2 if channel == 1 else 4)
        signal += 800
        noisy = signal + rng.normal(0, 1, signal.shape).astype(np.float32) * np.sqrt(signal + 25)
        data = np.clip(noisy, 0, 65535).astype(np.uint16)
        hdu = _fits.PrimaryHDU(data)
        hdu.header["BAYERPAT"] = "RGGB"
        path = directory / f"frame{i:03d}.fits"
        hdu.writeto(path)
        paths.append(path)
        print(f"  made {path.name}", flush=True)
    return paths


def run(paths: list[Path], previews: Path) -> dict[str, Any]:
    per_step: dict[str, list[float]] = {step: [] for step in STEPS}
    totals: list[float] = []
    preview_times: list[float] = []
    outcomes: list[str] = []
    for i, path in enumerate(paths):
        added = stack.add_frame(
            "bench",
            str(path),
            None,
            new=i == 0,
            preview_path=str(previews / f"stack{i}.jpg"),
        )
        start = time.perf_counter()
        pipeline.analyze(str(path), str(previews / f"preview{i}.jpg"))
        preview_times.append(time.perf_counter() - start)
        outcome = (
            f"in, shift {added.shift}, rotation {added.rotation}, {added.stars} stars"
            if added.accepted
            else f"out: {added.reason}"
        )
        outcomes.append(outcome)
        print(f"  {path.name}: {added.seconds:.2f} s, {outcome}", flush=True)
        if i == 0:
            continue  # the first frame registers nothing and allocates the stack
        for step in STEPS:
            if step in added.steps:
                per_step[step].append(added.steps[step])
        totals.append(added.seconds)
    held = stack._stacks["bench"]  # pyright: ignore[reportPrivateUsage]
    arrays = sum(a.nbytes for a in (held.mean, held.m2, held.count) if a is not None)
    return {
        "host": platform.node(),
        "machine": platform.machine(),
        "frames": len(paths),
        "accepted": held.frames,
        "steps_ms": {
            step: round(statistics.median(values) * 1000, 1)
            for step, values in per_step.items()
            if values
        },
        "stack_ms": round(statistics.median(totals) * 1000, 1) if totals else None,
        "preview_ms": round(statistics.median(preview_times) * 1000, 1),
        "stack_arrays_mb": round(arrays / 2**20),
        # ru_maxrss is in KiB on Linux; this process does nothing but stack and preview.
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        "outcomes": outcomes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--frames", type=Path, help="stack these FITS files instead")
    parser.add_argument("--count", type=int, default=12, help="synthetic frames (default 12)")
    parser.add_argument("--json", type=Path, help="write the results here")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="stack-bench-") as scratch:
        work = Path(scratch)
        if args.frames is not None:
            paths = sorted(args.frames.glob("*.fit*"))
            if len(paths) < 2:
                parser.error(f"need at least two FITS files in {args.frames}")
        else:
            print(f"making {args.count} synthetic {WIDTH}x{HEIGHT} RGGB frames", flush=True)
            paths = synthetic(work, args.count)
        print("stacking (in a fresh process, as the worker)", flush=True)
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
            results = pool.submit(run, paths, work).result()
    print()
    print(
        f"{results['host']} ({results['machine']}), {results['frames']} frames, "
        f"{results['accepted']} stacked"
    )
    print("| step | median ms |")
    print("|---|---|")
    for step, ms in results["steps_ms"].items():
        print(f"| {step} | {ms} |")
    print(f"| **stack, per frame** | **{results['stack_ms']}** |")
    print(f"| preview (for comparison) | {results['preview_ms']} |")
    print(
        f"stack arrays: {results['stack_arrays_mb']} MB; "
        f"peak RSS of this process: {results['peak_rss_mb']} MB"
    )
    if args.json is not None:
        args.json.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
