"""When and where the twilight sky makes flats (ADR 0036).

The sky is evenly lit enough for flats, and dim enough for exposures of a second
or more, while the Sun is between 1° and 10° below the horizon. The flattest
part is high up, opposite the Sun.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np

from nocs.devices import Coordinates, Location
from nocs.mount.coords import horizontal_to_jnow, jnow_to_j2000
from nocs.sky.ephemeris import sky

SUN_HIGH = -1.0
SUN_LOW = -10.0
FLAT_ALTITUDE = 75.0
STEP = 60.0
"""Seconds between the Sun's positions when looking for the windows."""

NARROWBAND = frozenset(
    {"ha", "h-alpha", "halpha", "h_alpha", "oiii", "o3", "o-iii", "sii", "s2", "s-ii", "nii", "hb"}
)

type Phase = Literal["dusk", "dawn"]


@dataclass(frozen=True, slots=True)
class Window:
    phase: Phase
    start: datetime
    end: datetime


def windows(site: Location, now: datetime, hours: float = 24) -> list[Window]:
    """The dusk and dawn windows from now on (one already open starts now)."""
    base = now.timestamp()
    times = base + np.arange(0, hours * 3600 + STEP, STEP)
    altitude = np.asarray(sky(site, times).sun.alt, dtype=np.float64)
    inside = (altitude <= SUN_HIGH) & (altitude >= SUN_LOW)
    found: list[Window] = []
    i = 0
    while i < len(times):
        if not inside[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(times) and inside[j + 1]:
            j += 1
        if j > i:
            phase: Phase = "dusk" if altitude[j] < altitude[i] else "dawn"
            found.append(Window(phase, _when(now, times[i] - base), _when(now, times[j] - base)))
        i = j + 1
    return found


def sun(site: Location, when: datetime) -> tuple[float, float]:
    """The Sun's altitude and azimuth, degrees."""
    position = sky(site, [when.timestamp()]).sun
    return float(position.alt[0]), float(position.az[0])


def phase(site: Location, when: datetime) -> Phase:
    """Whether the Sun is going down (dusk) or up (dawn)."""
    before, _ = sun(site, when - timedelta(minutes=1))
    after, _ = sun(site, when + timedelta(minutes=1))
    return "dusk" if after < before else "dawn"


def flat_spot(site: Location, when: datetime) -> Coordinates:
    """J2000 coordinates high up opposite the Sun, where the twilight sky is flattest."""
    _, azimuth = sun(site, when)
    jnow = horizontal_to_jnow(FLAT_ALTITUDE, (azimuth + 180) % 360, site, when)
    return jnow_to_j2000(jnow.ra, jnow.dec, when)


def ordered[T](filters: Iterable[T], name: Iterable[str | None], phase: Phase) -> list[T]:
    """Filters in the order the twilight needs them: the ones that pass the least light
    while the sky is brightest (first at dusk, last at dawn). Stable otherwise."""
    pairs = list(zip(filters, name, strict=True))
    narrow = [f for f, n in pairs if (n or "").strip().lower() in NARROWBAND]
    broad = [f for f, n in pairs if (n or "").strip().lower() not in NARROWBAND]
    return narrow + broad if phase == "dusk" else broad + narrow


def _when(now: datetime, seconds: float) -> datetime:
    return now + timedelta(seconds=float(seconds))
