"""From a FITS frame to a phone-sized preview and quality metrics (ADR 0012).

Runs in the imaging worker process, never on the event loop: everything here is
CPU-bound and blocking. Choices come from the Pi 5 spike: OpenCV for debayer,
downscale and JPEG; statistics on subsamples; ``sep`` on a 2x2-binned frame for
stars when it is large.
"""

from __future__ import annotations

import math
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import sep  # pyright: ignore[reportMissingTypeStubs]
from astropy.io import fits  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray

# astropy.io.fits and sep carry no usable type information. They are used only
# through these explicitly untyped handles, and every value taken from them is
# converted to a typed one at once.
_fits: Any = fits
_sep: Any = sep

PREVIEW_WIDTH = 1920
JPEG_QUALITY = 85
BIN_STARS_ABOVE = 4_000_000
"""Frames with more pixels than this are 2x2 binned for star detection."""
HISTOGRAM_BINS = 256
HISTOGRAM_TAIL = 0.005
"""Fraction of the data at each end (hot pixels, say) left out when choosing the range."""
HISTOGRAM_MARGIN = 0.3
"""Room at each side of the histogram's range, as a fraction of it."""

# FITS BAYERPAT -> OpenCV code producing BGR. OpenCV names patterns by a different
# corner: an RGGB sensor is OpenCV's "BG".
_DEBAYER: dict[str, int] = {
    "RGGB": cv2.COLOR_BayerBG2BGR,
    "BGGR": cv2.COLOR_BayerRG2BGR,
    "GRBG": cv2.COLOR_BayerGB2BGR,
    "GBRG": cv2.COLOR_BayerGR2BGR,
}

type Mono16 = NDArray[np.uint16]
type Image = NDArray[np.float32]


@dataclass(frozen=True, slots=True)
class Histogram:
    """Counts of the linear data (sampled) in equal bins over where the data is."""

    counts: list[int]
    start: int
    """Value (ADU) at the lower edge of the first bin."""
    step: int
    """Values per bin: a whole multiple of the data's quantization (16 for a 12-bit camera)."""
    minimum: int
    maximum: int
    """Darkest and brightest sampled values, which may lie outside the bins."""


@dataclass(frozen=True, slots=True)
class FrameAnalysis:
    preview: str
    """Path of the JPEG written."""
    width: int
    height: int
    color: bool
    stars: int
    hfr: float | None
    """Median half-flux radius in unbinned pixels; None without stars."""
    histogram: Histogram
    seconds: float
    """Processing time."""


@dataclass(frozen=True, slots=True)
class StarMetrics:
    stars: int
    hfr: float | None
    """Median half-flux radius in unbinned pixels; None without stars."""
    seconds: float
    """Processing time."""


def warm_up() -> None:
    """Nothing to do: importing this module in the worker loads OpenCV, sep and astropy."""


def analyze(
    fits_path: str, preview_path: str, bayer: str | None = None, width: int = PREVIEW_WIDTH
) -> FrameAnalysis:
    """Write a stretched JPEG preview of a FITS frame, at most ``width`` pixels
    across, and measure its stars.

    ``bayer`` is used when the file does not say (``BAYERPAT``); no pattern at
    all means mono.
    """
    start = time.perf_counter()
    data, header_bayer, bottom_up = load(fits_path)
    pattern = (header_bayer or bayer or "").upper() or None
    if pattern is not None and pattern not in _DEBAYER:
        raise ValueError(f"unsupported Bayer pattern {pattern}")

    histogram = measure_histogram(data)
    stars, hfr = measure_stars(data, binned=pattern is not None or data.size > BIN_STARS_ABOVE)

    image: NDArray[np.uint16] = (
        np.asarray(cv2.cvtColor(data, _DEBAYER[pattern]), dtype=np.uint16)
        if pattern is not None
        else data
    )
    stretched = stretch(_downscale(image, width))
    if bottom_up:
        stretched = np.ascontiguousarray(stretched[::-1])
    _write_jpeg(Path(preview_path), stretched)
    return FrameAnalysis(
        preview=preview_path,
        width=int(stretched.shape[1]),
        height=int(stretched.shape[0]),
        color=pattern is not None,
        stars=stars,
        hfr=hfr,
        histogram=histogram,
        seconds=round(time.perf_counter() - start, 3),
    )


def measure_frame(fits_path: str, bayer: str | None = None) -> StarMetrics:
    """Only the stars of a FITS frame, for workflows that need no preview (autofocus)."""
    start = time.perf_counter()
    data, header_bayer, _ = load(fits_path)
    color = bool(header_bayer or bayer)
    stars, hfr = measure_stars(data, binned=color or data.size > BIN_STARS_ABOVE)
    return StarMetrics(stars=stars, hfr=hfr, seconds=round(time.perf_counter() - start, 3))


def level(fits_path: str, bayer: str | None = None) -> float:
    """A flat's level: the median of the frame, or of its strongest Bayer channel, in
    ADU of the 16-bit scale (ADR 0036). Every fourth pixel of a channel is enough."""
    data, header_bayer, _ = load(fits_path)
    if header_bayer or bayer:
        channels = [data[y::2, x::2][::2, ::2] for y in (0, 1) for x in (0, 1)]
    else:
        channels = [data[::2, ::2]]
    return max(float(np.median(channel)) for channel in channels)


def load(path: str) -> tuple[Mono16, str | None, bool]:
    """Pixels as 16-bit, the Bayer pattern if the header has one, and whether rows are bottom-up."""
    with _fits.open(path, memmap=False) as hdul:
        hdu = hdul[0]
        raw = np.asarray(hdu.data)
        bayer = str(hdu.header.get("BAYERPAT", "")).strip()
        row_order = str(hdu.header.get("ROWORDER", "TOP-DOWN")).strip().upper()
    if raw.ndim != 2:
        raise ValueError(f"expected a 2-D image, got shape {raw.shape}")
    # 8-bit frames are scaled to 16 bits so one code path handles every camera.
    if raw.dtype == np.uint8:
        data: Mono16 = raw.astype(np.uint16) * np.uint16(256)
    else:
        data = np.clip(raw, 0, 65535).astype(np.uint16)
    return data, bayer or None, row_order == "BOTTOM-UP"


def stretch(
    image: Image, target_background: float = 0.25, shadows_sigma: float = -2.8
) -> NDArray[np.uint8]:
    """Automatic midtones-transfer stretch to 8 bits, each channel on its own.

    The usual "screen stretch": clip shadows a few MADs below the median and map
    the median to ``target_background``. Statistics come from a subsample.
    """
    channels = image[..., np.newaxis] if image.ndim == 2 else image
    out = np.empty(channels.shape, dtype=np.uint8)
    for c in range(channels.shape[2]):
        data = channels[..., c] / np.float32(65535.0)
        sample = data[::2, ::2]
        median = float(np.median(sample))
        mad = float(np.median(np.abs(sample - median))) * 1.4826
        shadows = min(max(median + shadows_sigma * mad, 0.0), 1.0)
        scale = max(1.0 - shadows, 1e-6)
        x = (median - shadows) / scale
        midtones = (
            x * (target_background - 1) / ((2 * target_background - 1) * x - target_background)
            if 0 < x < 1
            else 0.5
        )
        normalized = np.clip((data - shadows) / scale, 0.0, 1.0)
        mapped = (midtones - 1) * normalized / ((2 * midtones - 1) * normalized - midtones)
        out[..., c] = (np.clip(mapped, 0.0, 1.0) * 255).astype(np.uint8)
    return out[..., 0] if image.ndim == 2 else out


def measure_stars(data: Mono16, *, binned: bool) -> tuple[int, float | None]:
    """Star count and median HFR in unbinned pixels.

    A 2x2 bin is cheaper on large frames, and turns a Bayer mosaic into luminance.
    """
    image = data.astype(np.float32)
    factor = 1
    if binned:
        h, w = image.shape[0] // 2 * 2, image.shape[1] // 2 * 2
        image = image[:h, :w].reshape(h // 2, 2, w // 2, 2).sum(axis=(1, 3), dtype=np.float32)
        factor = 2
    image = np.ascontiguousarray(image)

    background = _sep.Background(image)
    subtracted: Image = image - np.asarray(background.back(), dtype=np.float32)
    _sep.set_extract_pixstack(2_000_000)
    objects = _sep.extract(subtracted, 5.0, err=float(background.globalrms), minarea=5)
    count = len(objects)
    if count == 0:
        return 0, None
    radii, _ = _sep.flux_radius(
        subtracted, objects["x"], objects["y"], 6.0 * objects["a"], 0.5, subpix=5
    )
    values = np.asarray(radii, dtype=np.float64)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size == 0:
        return count, None
    return count, round(float(np.median(values)) * factor, 3)


def measure_histogram(data: Mono16) -> Histogram:
    """Bins over the data's range rather than the whole 16-bit one.

    A sky fills a few hundred ADU of 65536: equal bins over the full range would
    put it all in one or two. The range runs from the 0.5 % to the 99.5 % point
    with a margin at each side, so hot pixels and saturated stars do not stretch
    it; bins are a whole number of quantization steps wide, so scaled 12- and
    14-bit data has no empty bins between its values.
    """
    per_value = np.bincount(data[::4, ::4].ravel(), minlength=65536)
    present = np.flatnonzero(per_value)
    if present.size == 0:  # an empty frame
        return Histogram([0] * HISTOGRAM_BINS, 0, 1, 0, 0)
    minimum, maximum = int(present[0]), int(present[-1])
    step = int(np.gcd.reduce(present)) if maximum > 0 else 1
    cumulative = np.cumsum(per_value)
    total = int(cumulative[-1])
    low = int(np.searchsorted(cumulative, total * HISTOGRAM_TAIL, side="right"))
    high = int(np.searchsorted(cumulative, total * (1 - HISTOGRAM_TAIL)))
    margin = (high - low + 1) * HISTOGRAM_MARGIN
    start = max(0.0, low - margin)
    end = min(65536.0, high + 1 + margin)
    width = max(step, math.ceil((end - start) / HISTOGRAM_BINS / step) * step)
    first = int(start) // step * step
    first = max(0, min(first, 65536 - width * HISTOGRAM_BINS))
    window = np.zeros(width * HISTOGRAM_BINS, dtype=np.int64)
    available = per_value[first : first + window.size]
    window[: available.size] = available
    counts = window.reshape(HISTOGRAM_BINS, width).sum(axis=1)
    return Histogram([int(c) for c in counts], first, width, minimum, maximum)


def _downscale(image: NDArray[np.uint16], most: int = PREVIEW_WIDTH) -> Image:
    height, width = image.shape[:2]
    pixels = image.astype(np.float32)
    if width <= most:
        return pixels
    size = (most, max(1, round(height * most / width)))
    return np.asarray(cv2.resize(pixels, size, interpolation=cv2.INTER_AREA), dtype=np.float32)


def _write_jpeg(path: Path, image: NDArray[np.uint8]) -> None:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError("JPEG encoding failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(encoded.tobytes())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
