"""Registration of a frame on a reference by its stars (ADR 0037).

Stars come from ``sep``; the brightest of each frame form triangles with their
nearest neighbours, and triangles are compared by the ratios of their sides, which
neither a shift, a rotation nor a change of scale alter. Each pair of similar
triangles votes for three pairs of stars; the pairs with most votes go to OpenCV's
RANSAC for a similarity (rotation, uniform scale, shift), which a least-squares fit
over every star it then pairs refines.

A similarity cannot mirror: a frame mirrored relative to its reference (another
optical train) fails, and says so.

Runs in the imaging worker: blocking and CPU-bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Any, cast

import cv2
import numpy as np
import sep  # pyright: ignore[reportMissingTypeStubs]
from numpy.typing import NDArray

_sep: Any = sep  # untyped library; see nocs.imaging.pipeline

STARS = 50
"""Brightest stars used to register a frame."""
NEIGHBOURS = 5
"""Each star makes triangles with this many of its nearest stars."""
EDGE = 8
"""Pixels from the border inside which stars are ignored (cut off, unreliable)."""
SHORTEST_SIDE = 4.0
"""Triangles with a side shorter than this (pixels) are too uncertain to compare."""
INVARIANT_TOLERANCE = 0.01
"""How far two triangles' side ratios may differ and still be the same triangle."""
RANSAC_PIXELS = 2.0
"""A star pair further than this from the RANSAC model is an outlier."""
PAIR_PIXELS = 1.5
"""After RANSAC, a frame star within this of a reference star (transformed) pairs with it."""
MIN_INLIERS = 6
MIN_INLIER_FRACTION = 0.3
"""Of the candidate pairs, the fraction RANSAC must keep."""
SCALE_TOLERANCE = 0.005
"""How far the fitted scale may be from 1 (the same optics)."""
MAX_RMS = 1.0
"""Pixels: the largest acceptable residual of the paired stars."""

type Floats = NDArray[np.float64]


class RegistrationError(Exception):
    """The frame could not be registered; the message says why, for the user."""


@dataclass(frozen=True, slots=True)
class Stars:
    """Positions (0-based pixels) and fluxes, brightest first."""

    x: Floats
    y: Floats
    flux: Floats

    def __len__(self) -> int:
        return int(self.x.size)

    def points(self) -> Floats:
        return np.column_stack((self.x, self.y))


@dataclass(frozen=True, slots=True)
class Transform:
    """A similarity from a frame's pixels to its reference's:
    ``x' = a*x - b*y + tx``, ``y' = b*x + a*y + ty``."""

    a: float
    b: float
    tx: float
    ty: float

    @staticmethod
    def identity() -> Transform:
        return Transform(1.0, 0.0, 0.0, 0.0)

    @staticmethod
    def of(rotation: float, shift: tuple[float, float], scale: float = 1.0) -> Transform:
        """Rotation in degrees (turning x towards y), about the pixel origin."""
        angle = math.radians(rotation)
        return Transform(scale * math.cos(angle), scale * math.sin(angle), shift[0], shift[1])

    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def rotation(self) -> float:
        """Degrees, -180 to 180."""
        return math.degrees(math.atan2(self.b, self.a))

    @property
    def shift(self) -> tuple[float, float]:
        return self.tx, self.ty

    def matrix(self) -> Floats:
        """The 2x3 matrix ``cv2.warpAffine`` takes to move the frame onto the reference."""
        return np.array([[self.a, -self.b, self.tx], [self.b, self.a, self.ty]])

    def apply(self, points: Floats) -> Floats:
        x, y = points[:, 0], points[:, 1]
        return np.column_stack(
            (self.a * x - self.b * y + self.tx, self.b * x + self.a * y + self.ty)
        )


@dataclass(frozen=True, slots=True)
class Registration:
    transform: Transform
    stars: int
    """Star pairs the final fit used."""
    rms: float
    """Residual of those pairs, pixels."""


def find_stars(image: NDArray[np.float32], most: int = STARS) -> Stars:
    """The ``most`` brightest stars of a (luminance) image, away from its edges."""
    data = np.ascontiguousarray(image, dtype=np.float32)
    background = _sep.Background(data)
    subtracted: NDArray[np.float32] = data - np.asarray(background.back(), dtype=np.float32)
    _sep.set_extract_pixstack(2_000_000)
    objects = _sep.extract(subtracted, 5.0, err=float(background.globalrms), minarea=5)
    if len(objects) == 0:
        return _no_stars()
    x = np.asarray(objects["x"], dtype=np.float64)
    y = np.asarray(objects["y"], dtype=np.float64)
    flux = np.asarray(objects["flux"], dtype=np.float64)
    a = np.asarray(objects["a"], dtype=np.float64)
    height, width = data.shape
    keep = (x >= EDGE) & (x < width - EDGE) & (y >= EDGE) & (y < height - EDGE)
    keep &= np.isfinite(flux) & (flux > 0)
    order = np.argsort(-flux[keep])[:most]
    x, y, flux, a = x[keep][order], y[keep][order], flux[keep][order], a[keep][order]
    if x.size == 0:
        return _no_stars()
    # Windowed centroids: a tenth of a pixel better than the isophotal barycentre.
    sigma = np.clip(2.0 * a / 2.3548 * 2.0, 0.5, 10.0)
    wx, wy, flags = _sep.winpos(subtracted, x, y, sigma)
    wx = np.asarray(wx, dtype=np.float64)
    wy = np.asarray(wy, dtype=np.float64)
    good = (np.asarray(flags) == 0) & (np.hypot(wx - x, wy - y) < 1.5)
    x = np.where(good, wx, x)
    y = np.where(good, wy, y)
    return Stars(x, y, flux)


def register(frame: Stars, reference: Stars) -> Registration:
    """The similarity that takes ``frame``'s stars onto ``reference``'s.

    Raises ``RegistrationError`` with the reason when there is none worth trusting.
    """
    if len(frame) < MIN_INLIERS or len(reference) < MIN_INLIERS:
        raise RegistrationError(f"too few stars ({min(len(frame), len(reference))})")
    try:
        return _register(frame, reference)
    except RegistrationError as error:
        mirrored = Stars(-frame.x, frame.y, frame.flux)
        try:
            _register(mirrored, reference)
        except RegistrationError:
            raise error from None
        raise RegistrationError(
            "the frame is a mirror image of the reference: did the optical train change?"
        ) from None


def _register(frame: Stars, reference: Stars) -> Registration:
    pairs = _candidate_pairs(frame, reference)
    if len(pairs) < MIN_INLIERS:
        raise RegistrationError(f"no star pattern in common ({len(pairs)} pairs)")
    source = frame.points()[pairs[:, 0]]
    target = reference.points()[pairs[:, 1]]
    # OpenCV's stubs say nothing of the Nones it returns when it finds no model.
    outcome = cast(
        tuple[object, object],
        cv2.estimateAffinePartial2D(
            source.astype(np.float32),
            target.astype(np.float32),
            method=cv2.RANSAC,
            ransacReprojThreshold=RANSAC_PIXELS,
            maxIters=2000,
            confidence=0.999,
        ),
    )
    model, inliers = outcome
    if model is None or inliers is None:
        raise RegistrationError("no star pattern in common")
    kept = int(np.count_nonzero(cast(NDArray[np.uint8], inliers)))
    if kept < MIN_INLIERS or kept < MIN_INLIER_FRACTION * len(pairs):
        raise RegistrationError(f"no star pattern in common ({kept} of {len(pairs)} pairs)")
    m = np.asarray(cast(Floats, model), dtype=np.float64)
    transform = Transform(float(m[0, 0]), float(m[1, 0]), float(m[0, 2]), float(m[1, 2]))
    # Refine on every star the model pairs, not only the voted ones; twice, as the
    # first refinement may pair a few more.
    count, rms = 0, math.inf
    for _ in range(2):
        source, target = _pair_by_position(frame, reference, transform)
        if len(source) < MIN_INLIERS:
            break
        transform = _fit(source, target)
        residual = transform.apply(source) - target
        count, rms = len(source), float(np.sqrt(np.mean(np.sum(residual**2, axis=1))))
    if count < MIN_INLIERS:
        raise RegistrationError(f"too few stars in common ({count})")
    if abs(transform.scale - 1) > SCALE_TOLERANCE:
        raise RegistrationError(f"the scale changed (x{transform.scale:.4f})")
    if rms > MAX_RMS:
        raise RegistrationError(f"stars do not line up ({rms:.2f} px)")
    return Registration(transform, count, round(rms, 3))


def _triangles(stars: Stars) -> tuple[NDArray[np.intp], Floats]:
    """Triangles of each star with its nearest neighbours: vertex indices ordered as
    opposite the shortest, middle and longest side, and the invariants
    (longest / middle, middle / shortest)."""
    points = stars.points()
    n = len(points)
    distances = np.hypot(*(points[:, None, :] - points[None, :, :]).transpose(2, 0, 1))
    neighbours = np.argsort(distances, axis=1)[:, 1 : NEIGHBOURS + 1]
    found: set[tuple[int, int, int]] = set()
    for i in range(n):
        for j, k in combinations(neighbours[i].tolist(), 2):
            found.add(tuple(sorted((i, int(j), int(k)))))  # pyright: ignore[reportArgumentType]
    if not found:
        return np.empty((0, 3), dtype=np.intp), np.empty((0, 2))
    vertices = np.array(sorted(found), dtype=np.intp)
    # Side opposite each vertex.
    sides = np.column_stack(
        (
            distances[vertices[:, 1], vertices[:, 2]],
            distances[vertices[:, 0], vertices[:, 2]],
            distances[vertices[:, 0], vertices[:, 1]],
        )
    )
    order = np.argsort(sides, axis=1)
    sides = np.take_along_axis(sides, order, axis=1)
    vertices = np.take_along_axis(vertices, order, axis=1)
    usable = sides[:, 0] >= SHORTEST_SIDE
    sides, vertices = sides[usable], vertices[usable]
    invariants = np.column_stack((sides[:, 2] / sides[:, 1], sides[:, 1] / sides[:, 0]))
    return vertices, invariants


def _candidate_pairs(frame: Stars, reference: Stars) -> NDArray[np.intp]:
    """Star pairs (frame index, reference index) voted for by similar triangles: for
    each frame star, the reference star it was paired with most, if more than once."""
    frame_vertices, frame_invariants = _triangles(frame)
    reference_vertices, reference_invariants = _triangles(reference)
    if len(frame_invariants) == 0 or len(reference_invariants) == 0:
        return np.empty((0, 2), dtype=np.intp)
    # The second ratio can be large for thin triangles: compare in log space, so
    # the tolerance is relative.
    a = np.log(frame_invariants)
    b = np.log(reference_invariants)
    distance = np.hypot(a[:, None, 0] - b[None, :, 0], a[:, None, 1] - b[None, :, 1])
    nearest = np.argmin(distance, axis=1)
    close = distance[np.arange(len(a)), nearest] < INVARIANT_TOLERANCE
    votes = np.zeros((len(frame), len(reference)), dtype=np.int32)
    matched_frame = frame_vertices[close]
    matched_reference = reference_vertices[nearest[close]]
    np.add.at(votes, (matched_frame.ravel(), matched_reference.ravel()), 1)
    best = np.argmax(votes, axis=1)
    strength = votes[np.arange(len(frame)), best]
    chosen = np.flatnonzero(strength >= 2)
    return np.column_stack((chosen, best[chosen])).astype(np.intp)


def _pair_by_position(
    frame: Stars, reference: Stars, transform: Transform
) -> tuple[Floats, Floats]:
    """Frame stars whose transformed position falls within ``PAIR_PIXELS`` of exactly
    one reference star nearest to it, and that star."""
    moved = transform.apply(frame.points())
    target = reference.points()
    distance = np.hypot(
        moved[:, None, 0] - target[None, :, 0], moved[:, None, 1] - target[None, :, 1]
    )
    nearest = np.argmin(distance, axis=1)
    close = distance[np.arange(len(moved)), nearest] < PAIR_PIXELS
    # One frame star per reference star: keep the closest.
    chosen: dict[int, int] = {}
    for i in np.flatnonzero(close).tolist():
        j = int(nearest[i])
        if j not in chosen or distance[i, j] < distance[chosen[j], j]:
            chosen[j] = int(i)
    frame_index = np.array(list(chosen.values()), dtype=np.intp)
    reference_index = np.array(list(chosen.keys()), dtype=np.intp)
    return frame.points()[frame_index], target[reference_index]


def _fit(source: Floats, target: Floats) -> Transform:
    """Least-squares similarity from ``source`` to ``target``."""
    x, y = source[:, 0], source[:, 1]
    ones, zeros = np.ones_like(x), np.zeros_like(x)
    design = np.vstack(
        (np.column_stack((x, -y, ones, zeros)), np.column_stack((y, x, zeros, ones)))
    )
    values = np.concatenate((target[:, 0], target[:, 1]))
    solution = np.linalg.lstsq(design, values, rcond=None)[0]
    return Transform(*(float(v) for v in solution))


def _no_stars() -> Stars:
    empty = np.empty(0, dtype=np.float64)
    return Stars(empty, empty, empty)
