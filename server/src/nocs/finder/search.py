"""The finder's geometry: offsets on the sky, the search's spiral and the camera's axes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nocs.devices import Coordinates

MOTION_RANGE = (0.5, 2.0)
"""How far the disc's motion per arcminute may be from what the plate scale says."""
LEAST_ANGLE = 60.0
"""Degrees the frame's east and north must at least be apart."""


@dataclass(frozen=True, slots=True)
class Offset:
    """A point of the sky from another one, arcminutes on the sky."""

    east: float
    north: float

    def __add__(self, other: Offset) -> Offset:
        return Offset(self.east + other.east, self.north + other.north)

    def __mul__(self, factor: float) -> Offset:
        return Offset(self.east * factor, self.north * factor)

    @property
    def size(self) -> float:
        return math.hypot(self.east, self.north)


def aim(body: Coordinates, offset: Offset) -> Coordinates:
    """``offset`` away from ``body`` (RA in hours, Dec in degrees)."""
    dec = min(max(body.dec + offset.north / 60, -90.0), 90.0)
    cos = max(math.cos(math.radians(dec)), 1e-6)
    return Coordinates((body.ra + offset.east / 60 / cos / 15) % 24, dec)


def offset_between(body: Coordinates, point: Coordinates) -> Offset:
    """Where ``point`` is from ``body``: the inverse of :func:`aim`."""
    hours = (point.ra - body.ra + 12) % 24 - 12
    return Offset(hours * 15 * 60 * math.cos(math.radians(point.dec)), (point.dec - body.dec) * 60)


def spiral(radius: float, step: float) -> list[Offset]:
    """Points ``step`` apart out to ``radius`` (arcminutes), from the centre outwards
    in square rings, each ring in order around it."""
    if step <= 0:
        raise ValueError("the step must be positive")
    points = [Offset(0.0, 0.0)]
    rings = math.ceil(radius / step - 1e-9)
    for k in range(1, rings + 1):
        ring = [
            (i, j)
            for i in range(-k, k + 1)
            for j in range(-k, k + 1)
            if max(abs(i), abs(j)) == k and math.hypot(i, j) * step <= radius + step / 2
        ]
        ring.sort(key=lambda p: math.atan2(p[1], p[0]) % (2 * math.pi))
        points += [Offset(i * step, j * step) for i, j in ring]
    return points


@dataclass(frozen=True, slots=True)
class Axes:
    """How the disc moves in the frame when the aim moves: pixels per arcminute that
    the aim moves east, and north (what PHD2's calibration measures with a star)."""

    east: tuple[float, float]
    north: tuple[float, float]

    def move(self, dx: float, dy: float) -> Offset:
        """The aim's move that moves the disc by (``dx``, ``dy``) pixels."""
        a, c = self.east
        b, d = self.north
        det = a * d - b * c
        if abs(det) < 1e-12:
            raise ValueError("the axes are parallel")
        return Offset((d * dx - b * dy) / det, (-c * dx + a * dy) / det)

    def problem(self, scale: float) -> str | None:
        """Why the axes cannot be right for a plate scale of ``scale`` pixels per
        arcminute, or ``None``."""
        low, high = MOTION_RANGE[0] * scale, MOTION_RANGE[1] * scale
        for name, (x, y) in (("east", self.east), ("north", self.north)):
            moved = math.hypot(x, y)
            if not low <= moved <= high:
                return (
                    f"moving the mount {name} moved the disc {moved:.2f} px per arcminute, "
                    f"not the {scale:.2f} of the plate scale"
                )
        dot = self.east[0] * self.north[0] + self.east[1] * self.north[1]
        cos = dot / (math.hypot(*self.east) * math.hypot(*self.north))
        if abs(cos) > math.cos(math.radians(LEAST_ANGLE)):
            return "moving the mount east and north moved the disc the same way"
        return None
