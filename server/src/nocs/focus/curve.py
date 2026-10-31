"""The V-curve: a hyperbola fitted to HFR against focuser position (ADR 0021).

Near focus, seeing rounds the tip of the V; far from it, the out-of-focus disk
grows linearly with the distance from focus. A hyperbola has both shapes::

    hfr(x) = a · sqrt(1 + ((x - c) / b)²)

with ``a`` the HFR at best focus, ``c`` the best position and ``b`` the steps at
which the HFR has grown by √2. Its square is a parabola in ``x``, so a first fit
is linear least squares on HFR² (no iterative solver needed, and no guess);
a few damped Gauss-Newton steps on the HFR itself then remove the bias that
squaring gives to the far, large points.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

REFINE_ITERATIONS = 30

type Vector = NDArray[np.float64]


class FitError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Hyperbola:
    a: float
    """HFR at best focus (px)."""
    b: float
    """Steps from best focus at which the HFR is √2 · a."""
    c: float
    """Best focus position (steps)."""

    def __call__(self, x: float) -> float:
        return self.a * math.sqrt(1 + ((x - self.c) / self.b) ** 2)

    def distance_for(self, hfr: float) -> float:
        """Steps from best focus at which the curve reaches ``hfr`` (0 at or below ``a``)."""
        ratio = hfr / self.a
        return self.b * math.sqrt(ratio * ratio - 1) if ratio > 1 else 0.0


@dataclass(frozen=True, slots=True)
class Fit:
    curve: Hyperbola
    r_squared: float
    """Share of the HFR's variance the curve explains (1 is perfect)."""


def fit_hyperbola(positions: Sequence[float], hfrs: Sequence[float]) -> Fit:
    """Fit a hyperbola to at least three points with positive HFR.

    Raises ``FitError`` when the points do not make a curve that opens upwards
    (a straight line, a hump, all equal).
    """
    if len(positions) != len(hfrs):
        raise ValueError("positions and HFRs differ in number")
    if len(positions) < 3:
        raise FitError("a curve needs at least three points")
    x: Vector = np.asarray(positions, dtype=np.float64)
    y: Vector = np.asarray(hfrs, dtype=np.float64)
    if not (np.all(np.isfinite(x)) and np.all(np.isfinite(y)) and np.all(y > 0)):
        raise FitError("HFRs must be positive numbers")
    # Positions are in the tens of thousands: centre and scale them so the normal
    # equations stay well conditioned.
    origin = float(np.mean(x))
    span = float(np.ptp(x)) / 2 or 1.0
    u: Vector = (x - origin) / span

    start = _linear_fit(u, y)
    if start is None:
        raise FitError("the points do not form a V")
    a, b, c = _refine(u, y, *start)
    curve = Hyperbola(a=a, b=b * span, c=c * span + origin)
    model = np.array([curve(float(p)) for p in x], dtype=np.float64)
    residual = float(np.sum((y - model) ** 2))
    total = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1 - residual / total if total > 0 else 0.0
    return Fit(curve=curve, r_squared=r_squared)


def _linear_fit(u: Vector, y: Vector) -> tuple[float, float, float] | None:
    """``(a, b, c)`` from least squares on y² = A·u² + B·u + C.

    Each row is weighted by 1/y²: an error δ in y is an error 2yδ in y², so
    unweighted, the most defocused points would decide the fit.
    """
    weight = 1 / (y * y)
    design = np.stack([u * u, u, np.ones_like(u)], axis=1) * weight[:, np.newaxis]
    solution = np.linalg.lstsq(design, y * y * weight, rcond=None)[0]
    big_a, big_b, big_c = (float(v) for v in solution)
    if not big_a > 0:
        return None
    c = -big_b / (2 * big_a)
    a_squared = big_c - big_b * big_b / (4 * big_a)
    if a_squared > 0:
        a = math.sqrt(a_squared)
        return a, a / math.sqrt(big_a), c
    # A sharp V whose tip the parabola overshoots: start from the lowest point and
    # the slope of the arms, and let the refinement do the rest.
    a = float(np.min(y))
    return a, a / math.sqrt(big_a), c


def _refine(u: Vector, y: Vector, a: float, b: float, c: float) -> tuple[float, float, float]:
    """Levenberg-Marquardt on the HFR itself, from the linear fit."""

    def residuals(a: float, b: float, c: float) -> Vector:
        return y - a * np.sqrt(1 + ((u - c) / b) ** 2)

    cost = float(np.sum(residuals(a, b, c) ** 2))
    damping = 1e-3
    for _ in range(REFINE_ITERATIONS):
        d = (u - c) / b
        s = np.sqrt(1 + d * d)
        jacobian = np.stack([s, -a * d * d / (b * s), -a * d / (b * s)], axis=1)
        gradient = jacobian.T @ residuals(a, b, c)
        normal = jacobian.T @ jacobian
        improved = converged = False
        while damping < 1e6:
            try:
                step = np.linalg.solve(normal + damping * np.diag(np.diag(normal)), gradient)
            except np.linalg.LinAlgError:
                damping *= 10
                continue
            na, nb, nc = a + float(step[0]), abs(b + float(step[1])), c + float(step[2])
            if na > 0 and nb > 0:
                new_cost = float(np.sum(residuals(na, nb, nc) ** 2))
                if new_cost < cost:
                    a, b, c, damping, improved = na, nb, nc, damping / 10, True
                    converged = cost - new_cost < 1e-12 * max(cost, 1e-12)
                    cost = new_cost
                    break
            damping *= 10
        if not improved or converged:
            break
    return a, b, c
