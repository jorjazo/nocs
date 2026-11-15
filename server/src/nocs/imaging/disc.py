"""Where the Sun's or the Moon's disc is in a frame, by its brightness alone (ADR 0049).

Runs in the imaging worker. The disc is the largest region above halfway between
the sky's level and the brightest pixels, of an area that fits the disc expected;
its centre is that of a circle of about the expected radius fitted to the region's
edge away from the frame's border: the lit limb, which a crescent's terminator and
a frame's edge leave out. RANSAC picks the circle the most edge points lie on (the
limb), least squares refines it. A disc a few pixels across is its centroid.

Positions are in pixels of the frame as the camera sent it (after its binning),
rows as stored in the file.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from nocs.imaging.pipeline import Mono16, load

FULL_SCALE = 65535.0
WORK_SIZE = 640
"""Pixels along the longest side the frame is reduced to first."""
CONTRAST = 0.03
"""Least difference between the sky and the brightest pixels, of the full scale."""
MIN_AREA = 6
"""Pixels (reduced) of the smallest region taken for a disc."""
LEAST_SHARE = 0.03
"""Of the expected disc's area: the smallest region taken (a sliver at the edge)."""
MOST_SHARE = 2.0
"""Of the expected disc's area: the largest region taken (a glow is not a disc)."""
LIMB_RADIUS = 4.0
"""Pixels (reduced): smaller discs take the region's centroid instead of a fit."""
RADIUS_RANGE = (0.75, 1.25)
"""The fitted radius against the expected one: the focal length may be a little off."""
RANSAC = 400
LEAST_INLIERS = 0.25
"""Share of the edge's points the limb's circle must pass through."""

type Floats = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class Disc:
    width: int
    height: int
    """The frame's size, pixels."""
    background: float
    """The frame's median level, a fraction of the full scale."""
    found: bool
    x: float | None = None
    y: float | None = None
    """The disc's centre, pixels from the first column and row; it may be outside."""
    radius: float | None = None
    """Pixels."""
    method: Literal["limb", "centroid"] | None = None
    seconds: float = 0.0
    """Processing time."""


def find_disc(fits_path: str, bayer: str | None, radius: float) -> Disc:
    """The disc in a FITS frame; ``radius`` is the disc's expected radius as a fraction
    of the frame's width."""
    start = time.perf_counter()
    data, header_bayer, _ = load(fits_path)
    disc = locate(data, color=bool(header_bayer or bayer), radius=radius * data.shape[1])
    return replace(disc, seconds=round(time.perf_counter() - start, 3))


def locate(data: Mono16, *, color: bool, radius: float) -> Disc:
    """The disc in a frame's pixels, expected ``radius`` pixels across (half of it)."""
    height, width = data.shape
    image = data.astype(np.float32)
    factor = 1.0
    if color:
        # A 2x2 mean turns the Bayer mosaic into luminance.
        h, w = height // 2 * 2, width // 2 * 2
        image = image[:h, :w].reshape(h // 2, 2, w // 2, 2).mean(axis=(1, 3), dtype=np.float32)
        factor = 2.0
    longest = max(image.shape)
    if longest > WORK_SIZE:
        size = (
            max(1, round(image.shape[1] * WORK_SIZE / longest)),
            max(1, round(image.shape[0] * WORK_SIZE / longest)),
        )
        factor *= image.shape[1] / size[0]
        image = np.asarray(cv2.resize(image, size, interpolation=cv2.INTER_AREA), dtype=np.float32)

    level = float(np.median(image))
    nothing = Disc(width, height, round(level / FULL_SCALE, 4), found=False)
    sky = float(np.percentile(image, 2))
    # The brightest pixels where a 3x3 median keeps them: hot pixels go, a disc of two
    # pixels across stays.
    peak = float(np.max(np.asarray(cv2.medianBlur(image, 3), dtype=np.float32)))
    darker = image[image <= level]
    noise = 1.4826 * float(np.median(np.abs(darker - np.median(darker))))
    if peak - sky < max(8 * noise, CONTRAST * FULL_SCALE):
        return nothing

    mask = np.asarray(image > (sky + peak) / 2, dtype=np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if count <= 1:
        return nothing
    areas = np.asarray(stats, dtype=np.int64)[1:, cv2.CC_STAT_AREA]
    label = 1 + int(np.argmax(areas))
    area = float(areas[label - 1])
    expected = radius / factor
    disc_area = math.pi * expected**2
    if area < max(MIN_AREA, LEAST_SHARE * disc_area) or area > max(
        MOST_SHARE * disc_area, 4 * MIN_AREA
    ):
        return nothing

    region = np.asarray(labels == label, dtype=np.uint8)
    contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = max((np.asarray(c, dtype=np.int32) for c in contours), key=lambda c: int(c.shape[0]))
    filled = np.zeros_like(region)
    cv2.drawContours(filled, [outline], -1, 1, thickness=cv2.FILLED)
    moments = cv2.moments(filled, binaryImage=True)
    centroid = (moments["m10"] / moments["m00"], moments["m01"] / moments["m00"])

    if expected < LIMB_RADIUS:
        cx, cy = centroid
        return _found(nothing, cx, cy, math.sqrt(area / math.pi), factor, "centroid")

    points = outline.reshape(-1, 2).astype(np.float64)
    rows, columns = image.shape
    inner = (
        (points[:, 0] > 1)
        & (points[:, 0] < columns - 2)
        & (points[:, 1] > 1)
        & (points[:, 1] < rows - 2)
    )
    circle = fit_limb(points[inner], expected, centroid)
    if circle is None:
        return nothing
    cx, cy, r = circle
    return _found(nothing, cx, cy, r, factor, "limb")


def fit_limb(
    points: Floats, radius: float, inside: tuple[float, float], seed: int = 0
) -> tuple[float, float, float] | None:
    """The circle of about ``radius`` that the most ``points`` lie on, with ``inside``
    within it: centre and radius, or ``None``."""
    n = int(points.shape[0])
    if n < 12:
        return None
    low, high = RADIUS_RANGE[0] * radius, RADIUS_RANGE[1] * radius
    tolerance = max(1.0, 0.04 * radius)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, n, size=(RANSAC, 3))
    a, b, c = points[picks[:, 0]], points[picks[:, 1]], points[picks[:, 2]]
    centres, radii = _circumcircles(a, b, c)
    there = np.asarray(inside, dtype=np.float64)
    usable = (
        np.isfinite(radii)
        & (radii >= low)
        & (radii <= high)
        & (np.hypot(*(centres - there).T) < radii)
    )
    if not usable.any():
        return None
    centres, radii = centres[usable], radii[usable]
    distances = np.hypot(
        points[np.newaxis, :, 0] - centres[:, 0, np.newaxis],
        points[np.newaxis, :, 1] - centres[:, 1, np.newaxis],
    )
    inliers = np.abs(distances - radii[:, np.newaxis]) < tolerance
    counts = inliers.sum(axis=1)
    best = int(np.argmax(counts))
    if counts[best] < max(10, LEAST_INLIERS * n):
        return None
    cx, cy, r = _refine(points[inliers[best]], (*centres[best], radii[best]))
    if not low <= r <= high or math.hypot(cx - inside[0], cy - inside[1]) >= r:
        cx, cy, r = float(centres[best, 0]), float(centres[best, 1]), float(radii[best])
    return cx, cy, r


def _circumcircles(a: Floats, b: Floats, c: Floats) -> tuple[Floats, Floats]:
    """Centres ``(k, 2)`` and radii of the circles through each three points."""
    ax, ay, bx, by, cx, cy = a[:, 0], a[:, 1], b[:, 0], b[:, 1], c[:, 0], c[:, 1]
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    a2, b2, c2 = ax**2 + ay**2, bx**2 + by**2, cx**2 + cy**2
    with np.errstate(divide="ignore", invalid="ignore"):
        ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
        uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    centres = np.stack([ux, uy], axis=1)
    radii = np.hypot(ax - ux, ay - uy)
    return centres, np.where(np.abs(d) > 1e-9, radii, np.nan)


def _refine(points: Floats, start: tuple[float, float, float]) -> tuple[float, float, float]:
    """Least squares of the points' distances to the circle (Gauss-Newton)."""
    cx, cy, r = start
    for _ in range(8):
        dx, dy = points[:, 0] - cx, points[:, 1] - cy
        distance = np.maximum(np.hypot(dx, dy), 1e-9)
        residual = distance - r
        jacobian = np.stack([-dx / distance, -dy / distance, -np.ones_like(distance)], axis=1)
        step = np.linalg.lstsq(jacobian, -residual, rcond=None)[0]
        cx, cy, r = cx + float(step[0]), cy + float(step[1]), r + float(step[2])
        if float(np.abs(step).max()) < 1e-3:
            break
    return cx, cy, r


def _found(
    nothing: Disc,
    x: float,
    y: float,
    radius: float,
    factor: float,
    method: Literal["limb", "centroid"],
) -> Disc:
    """From the reduced image's pixels (centres at whole numbers) to the frame's."""
    return replace(
        nothing,
        found=True,
        x=round((x + 0.5) * factor - 0.5, 2),
        y=round((y + 0.5) * factor - 0.5, 2),
        radius=round(radius * factor, 2),
        method=method,
    )
