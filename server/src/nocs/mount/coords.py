"""Coordinates for pointing the mount, through ERFA (pyerfa).

INDI mounts take apparent coordinates of the date ("JNow": true equator and
equinox, with precession, nutation and aberration). They are computed as libindi
does: ERFA's CIRS right ascension minus the equation of the origins. UT1 is taken
as UTC and polar motion as zero (both well under an arcsecond of pointing), and
refraction is ignored: altitudes are geometric.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import erfa  # pyright: ignore[reportMissingTypeStubs]

from nocs.devices import Coordinates, Horizontal, Location

# pyerfa has no type information: it is used only through this untyped handle, and
# what it returns is converted to floats at once.
_erfa: Any = erfa


def j2000_to_jnow(ra: float, dec: float, when: datetime) -> Coordinates:
    """ICRS (J2000) RA in hours and Dec in degrees, to JNow at ``when``."""
    _, _, tt1, tt2 = _dates(when)
    ri, di, eo = _erfa.atci13(_rad(ra * 15), _rad(dec), 0.0, 0.0, 0.0, 0.0, tt1, tt2)
    return _coordinates(float(ri) - float(eo), float(di))


def jnow_to_j2000(ra: float, dec: float, when: datetime) -> Coordinates:
    _, _, tt1, tt2 = _dates(when)
    eo = float(_erfa.eo06a(tt1, tt2))
    rc, dc = _erfa.atic13(_rad(ra * 15) + eo, _rad(dec), tt1, tt2)[:2]
    return _coordinates(float(rc), float(dc))


def horizontal_to_jnow(alt: float, az: float, site: Location, when: datetime) -> Coordinates:
    """Where a point of the local sky (azimuth from north through east) is in JNow."""
    utc1, utc2, tt1, tt2 = _dates(when)
    ri, di = _erfa.atoi13(
        "A", _rad(az), _rad(90 - alt), utc1, utc2, 0.0, *_observer(site), 0.0, 0.0, 0.0, 0.55
    )
    return _coordinates(float(ri) - float(_erfa.eo06a(tt1, tt2)), float(di))


def jnow_to_horizontal(ra: float, dec: float, site: Location, when: datetime) -> Horizontal:
    utc1, utc2, tt1, tt2 = _dates(when)
    ri = _rad(ra * 15) + float(_erfa.eo06a(tt1, tt2))
    aob, zob = _erfa.atio13(ri, _rad(dec), utc1, utc2, 0.0, *_observer(site), 0.0, 0.0, 0.0, 0.55)[
        :2
    ]
    return Horizontal(90 - math.degrees(float(zob)), math.degrees(float(aob)) % 360)


def sidereal_time(longitude: float, when: datetime) -> float:
    """Local apparent sidereal time in hours: a JNow RA's hour angle is this minus it."""
    utc1, utc2, tt1, tt2 = _dates(when)
    gst = float(_erfa.gst06a(utc1, utc2, tt1, tt2))
    return (math.degrees(gst) + longitude) / 15 % 24


def _dates(when: datetime) -> tuple[float, float, float, float]:
    """``when`` as ERFA's two-part UTC and TT dates."""
    t = when.astimezone(UTC)
    seconds = t.second + t.microsecond / 1e6
    utc1, utc2 = _erfa.dtf2d("UTC", t.year, t.month, t.day, t.hour, t.minute, seconds)
    tai1, tai2 = _erfa.utctai(utc1, utc2)
    tt1, tt2 = _erfa.taitt(tai1, tai2)
    return float(utc1), float(utc2), float(tt1), float(tt2)


def _observer(site: Location) -> tuple[float, float, float, float, float]:
    """Longitude, latitude, height and polar motion (none), as ERFA wants them."""
    return _rad(site.longitude), _rad(site.latitude), site.elevation, 0.0, 0.0


def _coordinates(ra: float, dec: float) -> Coordinates:
    return Coordinates(math.degrees(float(_erfa.anp(ra))) / 15 % 24, math.degrees(dec))


def _rad(degrees: float) -> float:
    return math.radians(degrees)
