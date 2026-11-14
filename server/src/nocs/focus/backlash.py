"""Measuring a focuser's backlash on an arm of the V-curve (ADR 0044).

Away from focus a star's HFR grows almost linearly with the defocus, so a frame
there tells where the optics are to a few steps: the ``Ruler``. A move after a
reversal that the optics follow only in part shows its lost motion as the
commanded steps less the ones the ruler measured.

Also the focuser's scale: microns of drawtube per step from the V's asymptote,
the critical focus zone in steps, the smallest significant step.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

HFR_OF_DISK = 1 / (2 * math.sqrt(2))
"""Half-flux radius of a uniformly lit disk, as a fraction of its diameter."""
WAVELENGTH = 0.55
"""Micrometres: the critical focus zone's wavelength (green)."""


class RulerError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Ruler:
    """Where the optics are from a frame's HFR, on one arm of the V.

    ``position = c0 + c1·h + c2·h²``, fitted by least squares on frames at known
    positions; ``noise`` is the residuals' standard deviation, in steps.
    """

    coefficients: tuple[float, float, float]
    noise: float
    low: float
    high: float
    """The HFRs the ruler was made from."""

    @classmethod
    def fit(cls, positions: Sequence[int], hfrs: Sequence[float]) -> Ruler:
        if len(positions) != len(hfrs):
            raise ValueError("one HFR per position")
        if len(positions) < 4:
            raise RulerError(f"{len(positions)} points on the arm (4 needed)")
        h = np.asarray(hfrs, dtype=float)
        x = np.asarray(positions, dtype=float)
        order = np.argsort(x)
        if np.any(np.diff(h[order]) * np.sign(h[order][-1] - h[order][0]) <= 0):
            raise RulerError("the HFR does not grow steadily along the arm")
        c2, c1, c0 = (float(v) for v in np.polyfit(h, x, 2))
        residuals = x - (c0 + c1 * h + c2 * h * h)
        noise = float(np.sqrt(np.sum(residuals**2) / (len(x) - 3)))
        return cls((c0, c1, c2), noise, float(h.min()), float(h.max()))

    def position(self, hfr: float) -> float:
        c0, c1, c2 = self.coefficients
        return c0 + c1 * hfr + c2 * hfr * hfr


def microns_per_step(a: float, b: float, focal_ratio: float, pixel_size: float) -> float:
    """Drawtube travel per step from a V's asymptote ``a/b`` (unbinned px per step).

    Far from focus a star is a disk of diameter Δ/N whose HFR is 0.354 of it.
    """
    if a <= 0 or b <= 0 or focal_ratio <= 0 or pixel_size <= 0:
        raise ValueError("the curve, the focal ratio and the pixel size must be positive")
    return (a / b) * focal_ratio * pixel_size / HFR_OF_DISK


def focus_zone(focal_ratio: float, microns: float) -> int:
    """The critical focus zone (4.88 λ N²), in steps of ``microns``."""
    return max(1, round(4.88 * WAVELENGTH * focal_ratio**2 / microns))


def overshoot_for(lost: Sequence[int], step: int, margin: float = 1.3) -> int:
    """An overshoot that takes up the largest motion lost, with ``margin``; at least
    one sweep ``step``. Rounded up to two significant digits."""
    largest = max((max(0, value) for value in lost), default=0)
    return max(step, round_up(margin * largest))


def min_step(noise: float) -> int:
    """The smallest move a frame on the arm tells from its noise (three standard deviations)."""
    return max(1, math.ceil(3 * noise))


def round_up(value: float) -> int:
    """Up to two significant digits: 1035 → 1100, 87 → 87, 0 → 0."""
    if value <= 0:
        return 0
    unit = 10 ** max(0, len(str(math.ceil(value))) - 2)
    return int(-(-value // unit) * unit)
