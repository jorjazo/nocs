"""Synthetic frames of the Sun or the Moon: a disc, lit whole or as a phase, on a sky."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray


def disc_frame(
    width: int = 1200,
    height: int = 800,
    *,
    x: float = 600.0,
    y: float = 400.0,
    radius: float = 120.0,
    brightness: float = 40000.0,
    sky: float = 1500.0,
    noise: float = 40.0,
    phase: float = 1.0,
    angle: float = 0.0,
    stars: int = 0,
    seed: int = 1,
) -> NDArray[np.uint16]:
    """A frame with a disc centred at (``x``, ``y``), possibly outside the frame.

    ``phase`` is the lit fraction of the diameter across the terminator (1: full, 0.5:
    a quarter, 0.2: a crescent), lit on the side ``angle`` (degrees from +x) points to.
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    dx, dy = xx - x, yy - y
    r2 = (dx**2 + dy**2) / max(radius, 1e-9) ** 2
    inside = r2 <= 1
    image = np.full((height, width), sky, dtype=np.float64)
    # Limb darkening, as the Sun shows it; the Moon's maria, a few darker patches.
    lit: NDArray[np.float64] = brightness * (0.6 + 0.4 * np.sqrt(np.clip(1 - r2, 0, 1)))
    if phase < 1:
        a = math.radians(angle)
        along = (dx * math.cos(a) + dy * math.sin(a)) / radius
        across = (-dx * math.sin(a) + dy * math.cos(a)) / radius
        # The terminator: an ellipse of semi-axes 1 and |1 - 2·phase| across the disc.
        edge = (1 - 2 * phase) * np.sqrt(np.clip(1 - across**2, 0, 1))
        inside &= along >= edge
    for _ in range(3):
        mx, my = x + rng.uniform(-0.5, 0.5) * radius, y + rng.uniform(-0.5, 0.5) * radius
        patch = ((xx - mx) ** 2 + (yy - my) ** 2) < (0.2 * radius) ** 2
        lit = np.asarray(np.where(patch, lit * 0.7, lit), dtype=np.float64)
    image = np.where(inside, sky + lit, image)
    for _ in range(stars):
        sx, sy = rng.uniform(0, width), rng.uniform(0, height)
        image += 20000 * np.exp(-((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * 1.5**2))
    image += rng.normal(0, noise, image.shape)
    return np.clip(image, 0, 65535).astype(np.uint16)


def bayer(frame: NDArray[np.uint16]) -> NDArray[np.uint16]:
    """The frame as an RGGB mosaic would record a grey scene: green a little brighter."""
    mosaic = frame.astype(np.float64)
    mosaic[0::2, 0::2] *= 0.8
    mosaic[1::2, 1::2] *= 0.7
    return np.clip(mosaic, 0, 65535).astype(np.uint16)
