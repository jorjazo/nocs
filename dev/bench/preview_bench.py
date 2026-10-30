# /// script
# requires-python = ">=3.12,<3.14"  # sep has no prebuilt wheels for 3.14 on arm64 yet
# dependencies = [
#     "astropy>=6.1",
#     "numpy>=2.0",
#     "opencv-python-headless>=4.10",
#     "pillow>=11.0",
#     "sep>=1.4",
# ]
# ///
"""Benchmark the preview pipeline and star metrics on full-size frames.

For each FITS in a samples directory, times every stage nocsd would run after a
frame arrives (load, debayer, downscale, stretch, encode) in alternative
implementations, plus star detection and HFR with sep. Prints a table and
writes JSON results.

Usage: uv run dev/bench/preview_bench.py <samples dir> [--repeat N] [--json out.json]
"""

import argparse
import io
import json
import platform
import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import sep
from astropy.io import fits
from PIL import Image

PREVIEW_WIDTH = 1920


def timed(fn: Callable[[], Any], repeat: int) -> tuple[float, Any]:
    """Median wall time in ms over ``repeat`` runs, and the last result."""
    times: list[float] = []
    result: Any = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        times.append((time.perf_counter() - start) * 1000)
    return statistics.median(times), result


def load(path: Path) -> np.ndarray:
    with fits.open(path, memmap=False) as hdul:
        return np.asarray(hdul[0].data)


def debayer_superpixel(raw: np.ndarray) -> np.ndarray:
    """2x2 superpixel debayer (RGGB): half resolution, very cheap."""
    r = raw[0::2, 0::2].astype(np.float32)
    g = (raw[0::2, 1::2].astype(np.float32) + raw[1::2, 0::2]) / 2
    b = raw[1::2, 1::2].astype(np.float32)
    return np.dstack([r, g, b])


def debayer_opencv(raw: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(raw.astype(np.uint16), cv2.COLOR_BayerRG2RGB)


def downscale_opencv(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    size = (PREVIEW_WIDTH, round(h * PREVIEW_WIDTH / w))
    return cv2.resize(img.astype(np.float32), size, interpolation=cv2.INTER_AREA)


def downscale_numpy(img: np.ndarray) -> np.ndarray:
    """Integer block-mean binning down to at most PREVIEW_WIDTH wide."""
    f = max(1, -(-img.shape[1] // PREVIEW_WIDTH))
    h, w = img.shape[0] // f * f, img.shape[1] // f * f
    img = img[:h, :w].astype(np.float32)
    shape = (h // f, f, w // f, f, *img.shape[2:])
    return img.reshape(shape).mean(axis=(1, 3))


def stretch(img: np.ndarray, target_bg: float = 0.25, clip_sigma: float = -2.8) -> np.ndarray:
    """Automatic midtones-transfer stretch (as common 'screen stretches' do) to uint8."""
    data = img.astype(np.float32)
    data /= max(float(data.max()), 1.0)
    median = float(np.median(data))
    mad = float(np.median(np.abs(data - median))) * 1.4826
    shadows = min(max(median + clip_sigma * mad, 0.0), 1.0)
    x = (median - shadows) / max(1 - shadows, 1e-6)
    m = x * (target_bg - 1) / ((2 * target_bg - 1) * x - target_bg) if 0 < x < 1 else 0.5
    data = np.clip((data - shadows) / max(1 - shadows, 1e-6), 0, 1)
    data = (m - 1) * data / ((2 * m - 1) * data - m)
    return (np.clip(data, 0, 1) * 255).astype(np.uint8)


def encode(img8: np.ndarray, fmt: str, quality: int) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(img8).save(buffer, format=fmt, quality=quality)
    return buffer.getvalue()


def stars(img: np.ndarray, bin2: bool) -> tuple[int, float]:
    data = np.ascontiguousarray(img, dtype=np.float32)
    if bin2:
        h, w = data.shape[0] // 2 * 2, data.shape[1] // 2 * 2
        data = np.ascontiguousarray(data[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3)))
    bkg = sep.Background(data)
    sub = data - bkg
    sep.set_extract_pixstack(2_000_000)
    objects = sep.extract(sub, 5, err=bkg.globalrms, minarea=5)
    if len(objects) == 0:
        return 0, float("nan")
    radii, _ = sep.flux_radius(sub, objects["x"], objects["y"], 6.0 * objects["a"], 0.5, subpix=5)
    hfr = float(np.median(radii)) * (2 if bin2 else 1)
    return len(objects), hfr


def bench_file(path: Path, bayer: bool, repeat: int) -> dict[str, Any]:
    r: dict[str, Any] = {"file": path.name, "bayer": bayer}
    r["load_ms"], raw = timed(lambda: load(path), repeat)
    r["shape"] = list(raw.shape)
    if bayer:
        r["debayer_superpixel_ms"], color = timed(lambda: debayer_superpixel(raw), repeat)
        r["debayer_opencv_ms"], _ = timed(lambda: debayer_opencv(raw), repeat)
        base = color
    else:
        base = raw
    r["downscale_opencv_ms"], small = timed(lambda: downscale_opencv(base), repeat)
    r["downscale_numpy_ms"], _ = timed(lambda: downscale_numpy(base), repeat)
    r["stretch_ms"], img8 = timed(lambda: stretch(small), repeat)
    r["encode_webp_ms"], webp = timed(lambda: encode(img8, "WEBP", 80), repeat)
    r["encode_jpeg_ms"], jpeg = timed(lambda: encode(img8, "JPEG", 85), repeat)
    r["webp_kb"], r["jpeg_kb"] = len(webp) // 1024, len(jpeg) // 1024
    mono = raw if not bayer else raw.astype(np.float32)
    r["stars_full_ms"], (r["stars_full"], r["hfr_full_px"]) = timed(lambda: stars(mono, False), 1)
    r["stars_bin2_ms"], (r["stars_bin2"], r["hfr_bin2_px"]) = timed(lambda: stars(mono, True), 1)
    debayer = r.get("debayer_superpixel_ms", 0.0)
    r["pipeline_preview_ms"] = round(
        r["load_ms"] + debayer + r["downscale_opencv_ms"] + r["stretch_ms"] + r["encode_jpeg_ms"]
    )
    return r


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("samples", type=Path)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    manifest = json.loads((args.samples / "manifest.json").read_text())
    results = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "opencv_threads": cv2.getNumThreads(),
        "files": [bench_file(args.samples / m["file"], m["bayer"], args.repeat) for m in manifest],
    }
    for r in results["files"]:
        print(f"\n{r['file']} {r['shape']}")
        for key, value in r.items():
            if key.endswith(("_ms", "_px", "_kb")) or key.startswith("stars_"):
                shown = (
                    f"{value:.0f}" if isinstance(value, float) and key.endswith("_ms") else value
                )
                print(f"  {key:24} {shown}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
