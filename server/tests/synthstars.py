"""Synthetic star fields with known geometry, for registration and stacking tests.

A ``Sky`` is a set of stars in the reference frame's pixels. ``render`` draws the
frame a ``Transform`` (frame → reference) describes: each star lands at the
inverse transform of its sky position. Frames can be mono or a Bayer mosaic with a
colour per star, with sky background, read and shot noise, hot pixels, vignetting
and a satellite trail.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from nocs.stacking.register import Transform

type Floats = NDArray[np.float64]

# Position in a 2x2 Bayer cell (row, column) of each colour, by pattern.
CELLS: dict[str, dict[str, list[tuple[int, int]]]] = {
    "RGGB": {"R": [(0, 0)], "G": [(0, 1), (1, 0)], "B": [(1, 1)]},
    "BGGR": {"B": [(0, 0)], "G": [(0, 1), (1, 0)], "R": [(1, 1)]},
    "GRBG": {"G": [(0, 0), (1, 1)], "R": [(0, 1)], "B": [(1, 0)]},
    "GBRG": {"G": [(0, 0), (1, 1)], "B": [(0, 1)], "R": [(1, 0)]},
}


@dataclass(frozen=True, slots=True)
class Sky:
    x: Floats
    y: Floats
    flux: Floats
    """Total counts of each star (all channels together)."""
    colour: Floats
    """Per star, the share of R, G and B (rows sum to 1)."""


def sky(count: int, width: int, height: int, *, seed: int = 1, margin: float = -200.0) -> Sky:
    """Stars over the frame and ``-margin`` pixels beyond it, so moved frames stay full;
    fluxes follow a power law, as real fields do (many faint, a few bright)."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(margin, width - margin, count)
    y = rng.uniform(margin, height - margin, count)
    flux = 3e3 * (1 - rng.uniform(0, 0.97, count)) ** -1.5
    colour = rng.dirichlet((6.0, 8.0, 5.0), count)
    return Sky(x, y, flux, colour)


def invert(transform: Transform) -> Transform:
    m = np.vstack((transform.matrix(), (0.0, 0.0, 1.0)))
    inverse = np.linalg.inv(m)
    return Transform(
        float(inverse[0, 0]), float(inverse[1, 0]), float(inverse[0, 2]), float(inverse[1, 2])
    )


def render(
    stars: Sky,
    width: int,
    height: int,
    transform: Transform | None = None,
    *,
    sigma: float = 1.6,
    background: float = 800.0,
    read_noise: float = 5.0,
    bayer: str | None = None,
    hot_pixels: int = 0,
    vignetting: float = 0.0,
    trail: tuple[float, float, float, float] | None = None,
    trail_level: float = 3000.0,
    seed: int = 2,
    noise: bool = True,
) -> NDArray[np.uint16]:
    """A 16-bit frame of ``stars`` as seen by a frame that ``transform`` takes onto the
    reference (identity: the reference itself).

    ``vignetting``: the fraction of light lost at the corners. ``trail``: a line
    (x0, y0, x1, y1) of ``trail_level`` counts per pixel across the frame.
    """
    rng = np.random.default_rng(seed)
    where = invert(transform or Transform.identity()).apply(np.column_stack((stars.x, stars.y)))
    signal = np.zeros((height, width), dtype=np.float64)
    weights = _colour_weights(stars.colour, bayer)
    radius = math.ceil(sigma * 5)
    for i in range(len(stars.x)):
        x, y = float(where[i, 0]), float(where[i, 1])
        x0, x1 = max(0, int(x) - radius), min(width, int(x) + radius + 1)
        y0, y1 = max(0, int(y) - radius), min(height, int(y) + radius + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        yy, xx = np.mgrid[y0:y1, x0:x1]
        r2 = (xx - x) ** 2 + (yy - y) ** 2
        star = stars.flux[i] / (2 * math.pi * sigma**2) * np.exp(-r2 / (2 * sigma**2))
        if weights is not None:
            star = star * weights[i][yy % 2, xx % 2]
        signal[y0:y1, x0:x1] += star
    signal += background
    if trail is not None:
        signal += trail_level * _line(width, height, trail)
    if vignetting:
        signal *= vignette(width, height, vignetting)
    image = rng.poisson(signal) + rng.normal(0, read_noise, signal.shape) if noise else signal
    if hot_pixels:
        image[rng.integers(0, height, hot_pixels), rng.integers(0, width, hot_pixels)] = 60000
    return np.clip(image, 0, 65535).astype(np.uint16)


def vignette(width: int, height: int, loss: float) -> Floats:
    """Light reaching each pixel, 1 at the centre and ``1 - loss`` at the corners."""
    yy, xx = np.mgrid[0:height, 0:width]
    r2 = ((xx - (width - 1) / 2) ** 2 + (yy - (height - 1) / 2) ** 2) / (
        ((width - 1) / 2) ** 2 + ((height - 1) / 2) ** 2
    )
    return 1.0 - loss * r2


def _colour_weights(colour: Floats, bayer: str | None) -> NDArray[np.float64] | None:
    """Per star, the weight of each position of a 2x2 Bayer cell: its colour's share
    of the star's light, split between that colour's positions."""
    if bayer is None:
        return None
    cells = CELLS[bayer]
    weights = np.zeros((len(colour), 2, 2))
    for channel, name in enumerate("RGB"):
        positions = cells[name]
        for row, column in positions:
            weights[:, row, column] = colour[:, channel] / len(positions)
    # Each pixel of a cell weighs 4 times its share: on average 1, so the flux is kept.
    return weights * 4


def _line(width: int, height: int, ends: tuple[float, float, float, float]) -> Floats:
    x0, y0, x1, y1 = ends
    yy, xx = np.mgrid[0:height, 0:width]
    dx, dy = x1 - x0, y1 - y0
    distance = np.abs(dy * (xx - x0) - dx * (yy - y0)) / math.hypot(dx, dy)
    return np.exp(-(distance**2) / 2.0)
