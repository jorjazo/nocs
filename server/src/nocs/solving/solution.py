"""A plate solution: where a frame points, its scale and its rotation on the sky.

ASTAP writes the solution as FITS WCS keywords (gnomonic projection, ``CD`` matrix)
in a ``.ini`` file next to the image. Positions are ICRS (J2000).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


class SolutionError(Exception):
    """The solver's output could not be read."""


@dataclass(frozen=True, slots=True)
class Solution:
    ra: float
    """Right ascension of the frame's centre, J2000, hours."""
    dec: float
    """Declination of the frame's centre, J2000, degrees."""
    scale: float
    """Arcseconds per pixel of the solved image."""
    rotation: float
    """Position angle of the top of the image as NOCS shows it (first row at the top,
    or the last one for a ``ROWORDER = BOTTOM-UP`` file), degrees east of north, 0 to 360.
    ASIAIR's camera angle is 360° minus this."""
    mirrored: bool
    """The image as shown is a mirror view of the sky (east to the right of north, as
    through a diagonal or an odd number of mirrors)."""
    width: int
    height: int
    wcs: Wcs

    @property
    def fov(self) -> tuple[float, float]:
        """Degrees across x and y."""
        return self.width * self.scale / 3600, self.height * self.scale / 3600

    def corners(self) -> list[tuple[float, float]]:
        """J2000 (hours, degrees) of the frame's corners, from its first pixel around."""
        w, h = self.width + 0.5, self.height + 0.5
        return [self.wcs.to_sky(x, y) for x, y in ((0.5, 0.5), (w, 0.5), (w, h), (0.5, h))]


@dataclass(frozen=True, slots=True)
class Wcs:
    """A gnomonic (TAN) world coordinate system, as in FITS: 1-based pixels, degrees."""

    crpix1: float
    crpix2: float
    crval1: float
    crval2: float
    cd1_1: float
    cd1_2: float
    cd2_1: float
    cd2_2: float

    def to_sky(self, x: float, y: float) -> tuple[float, float]:
        """J2000 RA (hours) and Dec (degrees) of pixel (x, y), 1-based."""
        dx, dy = x - self.crpix1, y - self.crpix2
        xi = math.radians(self.cd1_1 * dx + self.cd1_2 * dy)
        eta = math.radians(self.cd2_1 * dx + self.cd2_2 * dy)
        ra0, dec0 = math.radians(self.crval1), math.radians(self.crval2)
        denominator = math.cos(dec0) - eta * math.sin(dec0)
        ra = ra0 + math.atan2(xi, denominator)
        dec = math.atan2(math.sin(dec0) + eta * math.cos(dec0), math.hypot(xi, denominator))
        return math.degrees(ra) / 15 % 24, math.degrees(dec)


def read_ini(path: Path) -> dict[str, str]:
    """ASTAP's ``.ini`` result: ``KEY=value`` lines."""
    values: dict[str, str] = {}
    for line in path.read_text(errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def solution_from_ini(
    values: dict[str, str], width: int, height: int, *, bottom_up: bool = False
) -> Solution:
    """The solution in ASTAP's result for an image of ``width`` by ``height`` pixels.

    ``bottom_up``: the file's first row is the bottom of the image (``ROWORDER``),
    which decides which way is up.
    """
    try:
        wcs = Wcs(
            crpix1=float(values["CRPIX1"]),
            crpix2=float(values["CRPIX2"]),
            crval1=float(values["CRVAL1"]),
            crval2=float(values["CRVAL2"]),
            cd1_1=float(values["CD1_1"]),
            cd1_2=float(values["CD1_2"]),
            cd2_1=float(values["CD2_1"]),
            cd2_2=float(values["CD2_2"]),
        )
    except (KeyError, ValueError) as error:
        raise SolutionError(f"incomplete solution: {error}") from error
    determinant = wcs.cd1_1 * wcs.cd2_2 - wcs.cd1_2 * wcs.cd2_1
    if determinant == 0:
        raise SolutionError("degenerate solution")
    ra, dec = wcs.to_sky((width + 1) / 2, (height + 1) / 2)
    # The pixel y axis on the sky is CD's second column, as (east, north) components;
    # it points to the top of the image as shown only when rows are bottom-up.
    up = 1 if bottom_up else -1
    return Solution(
        ra=ra,
        dec=dec,
        scale=math.sqrt(abs(determinant)) * 3600,
        rotation=math.degrees(math.atan2(up * wcs.cd1_2, up * wcs.cd2_2)) % 360,
        # With y up, a direct view of the sky has east to the left of north: a negative
        # determinant. Rows shown top-down flip y, and the sign with it.
        mirrored=(determinant > 0) == bottom_up,
        width=width,
        height=height,
        wcs=wcs,
    )


def separation(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angle between two positions (RA in hours, Dec in degrees), degrees."""
    a1, d1, a2, d2 = (
        math.radians(ra1 * 15),
        math.radians(dec1),
        math.radians(ra2 * 15),
        math.radians(dec2),
    )
    # Haversine: accurate for the arcsecond offsets centring deals with.
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((a2 - a1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))
