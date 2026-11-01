"""Polar alignment: the mount's RA axis from three solved frames, and its error.

Directions are unit vectors in the site's equatorial frame of the date, which turns
with the Earth: x towards the meridian on the celestial equator (hour angle 0, Dec 0),
y towards the east point of the horizon (hour angle -6 h), z towards the north
celestial pole. The pole of the date is ±z and the zenith (cos φ, 0, sin φ) at
latitude φ; a solved frame becomes a direction with :func:`direction`.

Turning only the RA axis (a go to at the same Dec, or tracking) carries the camera
around that axis, so frames taken that way lie on a circle about it: the axis is the
normal of the plane through them (:func:`fit_axis`). Its error (:func:`polar_error`)
is taken against the elevated pole, in the same words in both hemispheres: altitude
(positive: the axis points above the pole) and azimuth on the sky (positive: the axis
points east of it).

The knobs turn the whole mount, its axis and the camera with it: the altitude knob
about a horizontal line square to the axis, the azimuth knob about the vertical
(:func:`turn`). A frame taken after turning them, with the tracking in between
accounted for (:func:`track`), tells how far each was turned (:func:`knobs`), and so
where the axis is now. That works where the two knobs move the frame in different
directions (:func:`sensitivity`): not near the zenith, nor due east or west.

Refraction is ignored: solved positions are taken as where the camera points, and
the target is the true pole of the date (at 30° of altitude refraction shows it
~1.7' higher).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from nocs.devices import Location
from nocs.mount.coords import j2000_to_jnow, sidereal_time

type Vector = NDArray[np.float64]

ARCMIN = math.radians(1 / 60)
SIDEREAL_RATE = 2 * math.pi / 86_164.0905
"""Radians per second the sky turns, and a tracking mount with it."""
MIN_SPREAD = math.radians(0.01)
"""Radians the fitted points must spread off a line through them, roughly: a guard
against points on one line or in one place, not a measure of a good fit."""
_STEP = 0.1
"""Arcminutes of knob turn for numerical derivatives."""


@dataclass(frozen=True, slots=True)
class PolarError:
    """Arcminutes from the axis to the elevated celestial pole of the date."""

    altitude: float
    """Positive: the axis points above the pole."""
    azimuth: float
    """On the sky; positive: the axis points east of the pole."""
    total: float


@dataclass(frozen=True, slots=True)
class Knobs:
    """Arcminutes the knobs moved the axis by."""

    altitude: float
    """Up positive."""
    azimuth: float
    """East positive, on the sky."""
    residual: float
    """Of the frame's move, the part that turning the knobs does not explain."""


def vector(hour_angle: float, dec: float) -> Vector:
    """Hour angle in hours (west positive), Dec in degrees, to a direction."""
    h, d = math.radians(hour_angle * 15), math.radians(dec)
    return np.array([math.cos(d) * math.cos(h), -math.cos(d) * math.sin(h), math.sin(d)])


def angles(v: Vector) -> tuple[float, float]:
    """A direction's hour angle (hours, -12..12) and Dec (degrees)."""
    x, y, z = (float(c) for c in _unit(v))
    return math.degrees(math.atan2(-y, x)) / 15, math.degrees(math.asin(max(-1.0, min(1.0, z))))


def direction(ra: float, dec: float, site: Location, when: datetime) -> Vector:
    """Where a solution (J2000 RA in hours, Dec in degrees) taken at ``when`` points."""
    jnow = j2000_to_jnow(ra, dec, when)
    return vector(sidereal_time(site.longitude, when) - jnow.ra, jnow.dec)


def pole(latitude: float) -> Vector:
    """The celestial pole above the horizon (the north one on the equator)."""
    return np.array([0.0, 0.0, 1.0 if latitude >= 0 else -1.0])


def zenith(latitude: float) -> Vector:
    phi = math.radians(latitude)
    return np.array([math.cos(phi), 0.0, math.sin(phi)])


def fit_axis(points: Sequence[Vector], latitude: float) -> Vector:
    """The axis the points turned about (at least three), towards the elevated pole."""
    if len(points) < 3:
        raise ValueError("an axis needs at least three points")
    stacked = np.array([_unit(p) for p in points])
    centred = stacked - stacked.mean(axis=0)
    _, spread, rows = np.linalg.svd(centred)
    if float(spread[1]) < MIN_SPREAD:
        raise ValueError("the points are too close together to find the axis")
    normal = _unit(rows[2])
    return normal if float(normal @ pole(latitude)) >= 0 else -normal


def polar_error(axis: Vector, latitude: float) -> PolarError:
    a = _unit(axis)
    altitude = math.degrees(math.asin(_clip(float(a @ zenith(latitude))))) - abs(latitude)
    azimuth = math.degrees(math.asin(_clip(float(a[1]))))
    total = math.degrees(math.acos(_clip(float(a @ pole(latitude)))))
    return PolarError(altitude * 60, azimuth * 60, total * 60)


def turn(
    v: Vector, axis: Vector, latitude: float, *, altitude: float = 0.0, azimuth: float = 0.0
) -> Vector:
    """``v`` after turning the knobs so that ``axis`` rises by ``altitude`` and then
    moves east by ``azimuth`` (arcminutes on the sky, at the axis)."""
    up = zenith(latitude)
    a = _unit(axis)
    across = np.cross(a, up)
    if float(np.linalg.norm(across)) < 1e-9:
        raise ValueError("the axis points at the zenith")
    across = _unit(across)
    v = _rotate(v, across, altitude * ARCMIN)
    a = _rotate(a, across, altitude * ARCMIN)
    # Turning about the vertical by θ moves the axis east by (up x a)·y θ, on the sky.
    east = float(np.cross(up, a)[1])
    if abs(east) < 1e-9:
        raise ValueError("the axis points at the zenith")
    return _rotate(v, up, azimuth * ARCMIN / east)


def track(v: Vector, axis: Vector, seconds: float) -> Vector:
    """Where tracking about ``axis`` carries ``v`` in ``seconds``."""
    north = _unit(axis) if float(axis[2]) >= 0 else -_unit(axis)
    return _rotate(v, north, -SIDEREAL_RATE * seconds)


def knobs(before: Vector, after: Vector, axis: Vector, latitude: float, seconds: float) -> Knobs:
    """How far the knobs were turned for a frame at ``before`` to land at ``after``,
    ``seconds`` of tracking about ``axis`` later."""
    tracked = track(before, axis, seconds)
    target = _unit(after)
    altitude = azimuth = 0.0
    for _ in range(6):
        landed = turn(tracked, axis, latitude, altitude=altitude, azimuth=azimuth)
        jacobian = _jacobian(tracked, axis, latitude, altitude, azimuth)
        step = np.linalg.lstsq(jacobian, target - landed, rcond=None)[0]
        altitude += float(step[0])
        azimuth += float(step[1])
        if math.hypot(float(step[0]), float(step[1])) < 1e-4:
            break
    landed = turn(tracked, axis, latitude, altitude=altitude, azimuth=azimuth)
    return Knobs(altitude, azimuth, _angle(landed, target) * 60)


def sensitivity(v: Vector, axis: Vector, latitude: float) -> float:
    """How far a frame at ``v`` moves for the knob turn it shows the least (same units):
    the smaller this, the more a solve's error grows into the knobs' (1/this times)."""
    jacobian = _jacobian(v, axis, latitude, 0.0, 0.0) / ARCMIN
    return float(np.linalg.svd(jacobian, compute_uv=False)[1])


def rotation(axis: Vector, start: Vector, end: Vector) -> float:
    """Degrees turned about ``axis`` from ``start`` to ``end``, westwards positive (as
    the hour angle grows)."""
    north = _unit(axis) if float(axis[2]) >= 0 else -_unit(axis)
    a = start - (start @ north) * north
    b = end - (end @ north) * north
    return -math.degrees(math.atan2(float(np.cross(a, b) @ north), float(a @ b)))


def _jacobian(v: Vector, axis: Vector, latitude: float, altitude: float, azimuth: float) -> Vector:
    """Change of the turned ``v`` per arcminute of each knob (3 x 2)."""
    here = turn(v, axis, latitude, altitude=altitude, azimuth=azimuth)
    up = turn(v, axis, latitude, altitude=altitude + _STEP, azimuth=azimuth)
    east = turn(v, axis, latitude, altitude=altitude, azimuth=azimuth + _STEP)
    return np.column_stack(((up - here) / _STEP, (east - here) / _STEP))


def _rotate(v: Vector, about: Vector, angle: float) -> Vector:
    """Rodrigues: ``v`` turned by ``angle`` radians about the unit vector ``about``."""
    c, s = math.cos(angle), math.sin(angle)
    return v * c + np.cross(about, v) * s + about * float(about @ v) * (1 - c)


def _angle(a: Vector, b: Vector) -> float:
    """Degrees between two directions."""
    a, b = _unit(a), _unit(b)
    return math.degrees(math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b)))


def _unit(v: Vector) -> Vector:
    return v / float(np.linalg.norm(v))


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, x))
