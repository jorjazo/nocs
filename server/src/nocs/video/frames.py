"""The video stream's frames as previews: what the eye needs to aim, expose and focus.

Frames arrive raw (INDI's ``.stream`` BLOBs: the pixels, row by row, with no header),
8 or 16 bits, mono, Bayer or RGB. A preview shows them linear, as recorded, never
stretched: a planet's disc must look as bright as it is, and a saturated one must
show it. Each comes with a histogram, the share of saturated pixels and a sharpness
number (the variance of the Laplacian), which grows as focus improves at the same
exposure and gain.

Everything here blocks (numpy, OpenCV): call it from a thread. OpenCV releases the GIL
in its heavy calls.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from numpy.typing import NDArray

PREVIEW_WIDTH = 1600
"""Wider frames are scaled down for the preview (not for the numbers)."""
JPEG_QUALITY = 85
SHARPNESS_PIXELS = 2_000_000
"""Sharpness is measured on at most this many pixels (larger frames are scaled down)."""
SATURATED = 0.98
"""Of the full scale: pixels at or above it count as saturated."""

# INDI's CFA type -> OpenCV code producing BGR. OpenCV names patterns by a different
# corner: an RGGB sensor is OpenCV's "BG".
_DEBAYER: dict[str, int] = {
    "RGGB": cv2.COLOR_BayerBG2BGR,
    "BGGR": cv2.COLOR_BayerRG2BGR,
    "GRBG": cv2.COLOR_BayerGB2BGR,
    "GBRG": cv2.COLOR_BayerGR2BGR,
}


class FrameError(ValueError):
    """The data does not fit the frame's size."""


@dataclass(frozen=True, slots=True)
class Rendered:
    jpeg: bytes
    width: int
    """Of the JPEG."""
    height: int
    frame_width: int
    """Of the frame as streamed."""
    frame_height: int
    depth: int
    """Bits per pixel of the frame: 8 or 16."""
    color: bool
    histogram: list[int]
    """256 bins of the brightest channel, 8-bit scale."""
    saturated: float
    """Share of the pixels (any channel) at the top of the scale, 0 to 1."""
    sharpness: float


def render(data: bytes, width: int, height: int, bayer: str | None) -> Rendered:
    """A preview of one raw frame of ``width`` by ``height`` pixels."""
    pixels = width * height
    if pixels <= 0 or len(data) % pixels:
        raise FrameError(f"{len(data)} bytes are no {width}x{height} frame")
    per_pixel = len(data) // pixels
    if per_pixel not in (1, 2, 3, 6):
        raise FrameError(f"{per_pixel} bytes per pixel")
    depth = 16 if per_pixel in (2, 6) else 8
    channels = 3 if per_pixel in (3, 6) else 1
    dtype = np.dtype("<u2") if depth == 16 else np.dtype(np.uint8)
    raw = np.frombuffer(data, dtype=dtype)
    frame = raw.reshape(height, width, channels) if channels == 3 else raw.reshape(height, width)
    full = 65535 if depth == 16 else 255
    saturated = float(np.count_nonzero(frame >= SATURATED * full)) / frame.size

    eight: NDArray[np.uint8] = (
        (frame >> 8).astype(np.uint8) if depth == 16 else frame.astype(np.uint8, copy=False)
    )
    code = _DEBAYER.get(bayer.upper()) if bayer and channels == 1 else None
    if code is not None and width >= 2 and height >= 2:
        image: NDArray[np.uint8] = np.asarray(cv2.cvtColor(eight, code), dtype=np.uint8)
    else:
        image = eight
    color = image.ndim == 3
    gray: NDArray[np.uint8] = (
        np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8) if color else image
    )
    brightest = image.max(axis=2) if color else image
    histogram = np.bincount(brightest.ravel(), minlength=256)
    sharpness = _sharpness(gray)

    shown = image
    if width > PREVIEW_WIDTH:
        size = (PREVIEW_WIDTH, max(1, round(height * PREVIEW_WIDTH / width)))
        shown = np.asarray(cv2.resize(image, size, interpolation=cv2.INTER_AREA), dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", shown, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise FrameError("JPEG encoding failed")
    return Rendered(
        encoded.tobytes(),
        shown.shape[1],
        shown.shape[0],
        width,
        height,
        depth,
        color,
        [int(c) for c in histogram],
        round(saturated, 6),
        sharpness,
    )


def _sharpness(gray: NDArray[np.uint8]) -> float:
    height, width = gray.shape
    if width < 3 or height < 3:
        return 0.0
    if width * height > SHARPNESS_PIXELS:
        scale = (SHARPNESS_PIXELS / (width * height)) ** 0.5
        size = (max(3, round(width * scale)), max(3, round(height * scale)))
        gray = np.asarray(cv2.resize(gray, size, interpolation=cv2.INTER_AREA), dtype=np.uint8)
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    return round(float(np.var(laplacian)), 2)
