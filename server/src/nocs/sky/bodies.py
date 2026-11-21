"""Where the Sun, the Moon and the planets are for the mount: JNow coordinates from a
site, now.

The ephemeris gives their topocentric geometric altitude and azimuth (the Moon's
parallax from the site included); :func:`nocs.mount.coords.horizontal_to_jnow`
turns those into the apparent coordinates of the date a mount takes, without
refraction, as every go to of NOCS.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from nocs.devices import Coordinates, Location
from nocs.mount.coords import horizontal_to_jnow
from nocs.sky.ephemeris import planet, sky


class Body(StrEnum):
    SUN = "sun"
    MOON = "moon"
    MERCURY = "mercury"
    VENUS = "venus"
    MARS = "mars"
    JUPITER = "jupiter"
    SATURN = "saturn"
    URANUS = "uranus"
    NEPTUNE = "neptune"


PLANETS = (
    Body.MERCURY,
    Body.VENUS,
    Body.MARS,
    Body.JUPITER,
    Body.SATURN,
    Body.URANUS,
    Body.NEPTUNE,
)


@dataclass(frozen=True, slots=True)
class BodyPosition:
    body: Body
    jnow: Coordinates
    """RA in hours, Dec in degrees, of the date."""
    alt: float
    """Geometric altitude, degrees."""
    az: float
    semidiameter: float
    """Degrees."""


def position(body: Body, site: Location, when: datetime) -> BodyPosition:
    """Where ``body`` is in ``site``'s sky at ``when``."""
    now = sky(site, [when.timestamp()])
    if body is Body.SUN:
        seen = now.sun
    elif body is Body.MOON:
        seen = now.moon
    else:
        seen = planet(now, body.value)
    alt, az = float(seen.alt[0]), float(seen.az[0])
    return BodyPosition(
        body,
        horizontal_to_jnow(alt, az, site, when),
        alt,
        az,
        float(seen.semidiameter[0]),
    )


def separation(a: Coordinates, b: Coordinates) -> float:
    """Degrees between two positions (RA in hours)."""
    d1, d2 = math.radians(a.dec), math.radians(b.dec)
    dra = math.radians((a.ra - b.ra) * 15)
    h = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(dra / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(h))))
