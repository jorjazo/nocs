"""Where the Sun, the Moon and the stars are in a site's sky, through ERFA (pyerfa).

Positions are computed for many instants at once (numpy arrays of Unix seconds):
one ERFA context per instant serves the Sun, the Moon and every target. As in
:mod:`nocs.mount.coords`, UT1 is taken as UTC and polar motion as zero.

The Sun comes from ``epv00`` and the Moon from ``moon98`` (a few arcseconds), with
the Moon's parallax from the site (up to a degree) applied in the local frame:
ERFA's star pipeline would treat it as an annual parallax.

Altitudes are geometric (no refraction); :func:`refraction` turns them into
apparent ones for a standard atmosphere at the site's elevation (Saemundsson's
formula). ERFA's own refraction is not used: it caps the zenith distance and is
~15' short at the horizon, where rise and set are decided.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import erfa  # pyright: ignore[reportMissingTypeStubs]
import numpy as np
from numpy.typing import NDArray

from nocs.devices import Location

# pyerfa has no type information: it is used only through this untyped handle, and
# what it returns is converted to float arrays at once.
_erfa: Any = erfa

type Floats = NDArray[np.float64]

AU_KM = 149_597_870.7
EARTH_RADIUS_KM = 6378.137
MOON_RADIUS_KM = 1737.4
SUN_RADIUS_KM = 695_700.0
SIDEREAL_DAY = 86_164.0905
"""Seconds."""
TEMPERATURE = 10.0
"""°C of the standard atmosphere, the almanacs' convention."""
_UNIX_EPOCH_JD = 2_440_587.5


@dataclass(frozen=True)
class Position:
    """Topocentric, degrees: geometric altitude, azimuth from north through east."""

    alt: Floats
    az: Floats


@dataclass(frozen=True)
class Body(Position):
    distance: Floats
    """Km from the site."""
    semidiameter: Floats
    """Degrees."""
    geocentric: Floats
    """Geocentric position, au, ICRS axes (shape ``(n, 3)``)."""


@dataclass(frozen=True)
class Sky:
    """A site's sky at some instants: ERFA's context for each, the Sun and the Moon."""

    site: Location
    times: Floats
    """Unix seconds."""
    sun: Body
    moon: Body
    astrom: Any
    """ERFA's star-independent context per instant (a structured array)."""

    @property
    def pressure(self) -> float:
        return pressure(self.site.elevation)

    def star(self, ra: Floats | float, dec: Floats | float) -> Position:
        """ICRS (J2000) RA in hours and Dec in degrees, at every instant.

        Arrays of shape ``(m, 1)`` give ``(m, n)`` positions for ``n`` instants.
        """
        az, zenith = _observe(
            self.astrom, np.radians(np.asarray(ra) * 15), np.radians(np.asarray(dec))
        )
        return Position(90 - np.degrees(zenith), np.degrees(az) % 360)

    def hour_angle(self, ra: Floats | float, dec: Floats | float) -> Floats:
        """Local apparent hour angle, radians in (-π, π]."""
        ri, _ = _erfa.atciq(
            np.radians(np.asarray(ra) * 15), np.radians(np.asarray(dec)), 0, 0, 0, 0, self.astrom
        )
        ha = np.asarray(self.astrom["eral"], dtype=np.float64) - np.asarray(ri, dtype=np.float64)
        return (ha + math.pi) % (2 * math.pi) - math.pi


def sky(site: Location, times: Floats | list[float]) -> Sky:
    t = np.atleast_1d(np.asarray(times, dtype=np.float64))
    days = t / 86400
    whole = np.floor(days)
    utc1, utc2 = _UNIX_EPOCH_JD + whole, days - whole
    tai1, tai2 = _erfa.utctai(utc1, utc2)
    tt1, tt2 = _erfa.taitt(tai1, tai2)
    # No pressure: ERFA adds no refraction (see the module's docstring).
    astrom = _erfa.apco13(
        utc1,
        utc2,
        0.0,
        math.radians(site.longitude),
        math.radians(site.latitude),
        site.elevation,
        0.0,
        0.0,
        0.0,
        TEMPERATURE,
        0.5,
        0.55,
    )[0]

    earth = np.asarray(_erfa.epv00(tt1, tt2)[0]["p"], dtype=np.float64)
    sun_geo = -earth
    sun_az, sun_zenith = _direction(astrom, sun_geo)
    sun_km = np.linalg.norm(sun_geo, axis=-1) * AU_KM
    sun = Body(
        90 - np.degrees(sun_zenith),
        np.degrees(sun_az) % 360,
        sun_km,
        np.degrees(np.arcsin(SUN_RADIUS_KM / sun_km)),
        sun_geo,
    )

    moon_geo = np.asarray(_erfa.moon98(tt1, tt2)["p"], dtype=np.float64)
    moon_az, moon_zenith = _direction(astrom, moon_geo)
    # Parallax: move the observer from the Earth's centre up to the site, along the
    # local vertical (the difference with the geocentric vertical is ~10" here).
    geo_km = np.linalg.norm(moon_geo, axis=-1) * AU_KM
    rho = EARTH_RADIUS_KM + site.elevation / 1000
    alt = math.pi / 2 - moon_zenith
    up, across = geo_km * np.sin(alt) - rho, geo_km * np.cos(alt)
    moon_km = np.hypot(up, across)
    moon = Body(
        np.degrees(np.arctan2(up, across)),
        np.degrees(moon_az) % 360,
        moon_km,
        np.degrees(np.arcsin(MOON_RADIUS_KM / moon_km)),
        moon_geo,
    )
    return Sky(site, t, sun, moon, astrom)


def refraction(altitude: Floats, pressure: float, temperature: float = TEMPERATURE) -> Floats:
    """Degrees to add to a geometric altitude (Saemundsson), for hPa and °C.

    About 34' at the horizon at sea level. Below -1.5° the formula means nothing,
    and the value there is kept.
    """
    h = np.maximum(altitude, -1.5)
    arcmin = 1.02 / np.tan(np.radians(h + 10.3 / (h + 5.11)))
    return arcmin / 60 * (pressure / 1010) * (283 / (273 + temperature))


def pressure(elevation: float) -> float:
    """hPa of the standard atmosphere at ``elevation`` metres."""
    return 1013.25 * (1 - 2.25577e-5 * max(elevation, 0.0)) ** 5.25588


def illumination(sun: Floats, moon: Floats) -> tuple[Floats, Floats]:
    """The Moon's illuminated fraction and phase from geocentric positions (au).

    The phase is the Moon's ecliptic longitude minus the Sun's, degrees in
    [0, 360): 0 new, 90 first quarter, 180 full, 270 last quarter.
    """
    to_sun = sun - moon
    cos_i = np.sum(to_sun * -moon, axis=-1) / (
        np.linalg.norm(to_sun, axis=-1) * np.linalg.norm(moon, axis=-1)
    )
    fraction = (1 + cos_i) / 2
    phase = (_longitude(moon) - _longitude(sun)) % 360
    return fraction, phase


def separation(a: Position, b: Position) -> Floats:
    """Degrees between two sets of directions (they broadcast)."""
    alt1, az1, alt2, az2 = (np.radians(x) for x in (a.alt, a.az, b.alt, b.az))
    cos = np.sin(alt1) * np.sin(alt2) + np.cos(alt1) * np.cos(alt2) * np.cos(az1 - az2)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


_OBLIQUITY = math.radians(23.439281)
"""Of J2000: enough to tell the Moon's phase (the quarters are within a minute)."""


def _longitude(p: Floats) -> Floats:
    """Ecliptic longitude (degrees) of ICRS vectors."""
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    return np.degrees(np.arctan2(y * math.cos(_OBLIQUITY) + z * math.sin(_OBLIQUITY), x))


def _observe(astrom: Any, rc: Floats, dc: Floats) -> tuple[Floats, Floats]:
    """Azimuth and geometric zenith distance (radians) of ICRS directions."""
    ri, di = _erfa.atciq(rc, dc, 0, 0, 0, 0, astrom)
    aob, zob = _erfa.atioq(ri, di, astrom)[:2]
    return np.asarray(aob, dtype=np.float64), np.asarray(zob, dtype=np.float64)


def _direction(astrom: Any, p: Floats) -> tuple[Floats, Floats]:
    """Azimuth and geocentric geometric zenith distance of geocentric vectors."""
    theta, phi = _erfa.c2s(p)
    return _observe(astrom, np.asarray(theta, dtype=np.float64), np.asarray(phi, dtype=np.float64))
