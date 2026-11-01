"""The sky a sequence's conditions and waits ask about (phase 5.9, on ``nocs.sky``).

Altitudes of targets are apparent (with refraction), as a horizon is measured; the
Sun's are geometric, as twilights are defined.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from nocs.devices import Location
from nocs.equipment import HorizonPoint
from nocs.mount.coords import j2000_to_jnow, sidereal_time
from nocs.sky import Darkness, horizon_altitude, night, tonight
from nocs.sky.almanac import TWILIGHTS
from nocs.sky.ephemeris import refraction, sky


@dataclass(frozen=True)
class Place:
    site: Location
    horizon: list[HorizonPoint] | None = None


def sun_altitude(place: Place, when: datetime) -> float:
    """Degrees, geometric."""
    return float(sky(place.site, [when.timestamp()]).sun.alt[0])


def dark(place: Place, when: datetime, darkness: Darkness) -> bool:
    """The Sun is below the end of ``darkness``'s twilight."""
    return sun_altitude(place, when) <= TWILIGHTS[darkness]


def dawn(place: Place, when: datetime, darkness: Darkness) -> datetime:
    """When the night ``when`` belongs to ends for ``darkness`` (or at sunrise, or at
    local noon, when the night never gets that dark or the Sun never rises)."""
    tonight_ = night(place.site, tonight(place.site, when))
    interval = tonight_.twilights[darkness]
    end = interval.end if interval is not None else tonight_.sunrise or tonight_.span.end
    return datetime.fromtimestamp(end, UTC)


def altitude(place: Place, ra: float, dec: float, when: datetime) -> tuple[float, float]:
    """A J2000 target's apparent altitude, and the horizon profile's at its azimuth."""
    chart = sky(place.site, [when.timestamp()])
    position = chart.star(ra, dec)
    geometric = position.alt[0]
    apparent = float(geometric + refraction(geometric, chart.pressure))
    limit = float(horizon_altitude(place.horizon, position.az)[0])
    return apparent, limit


def hour_angle(place: Place, ra: float, dec: float, when: datetime) -> float:
    """A J2000 target's hour angle at ``when``, hours from -12 to 12 (west positive)."""
    now = j2000_to_jnow(ra, dec, when)
    return (sidereal_time(place.site.longitude, when) - now.ra + 12) % 24 - 12
