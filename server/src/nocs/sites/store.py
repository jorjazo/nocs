"""Saved sites and the active one, on disk (ADR 0038).

``<config dir>/sites.json`` holds every site the owner saved, by an id NOCS gives it,
and the id of the active one: sites belong to the box, not to equipment profiles.
"""

from __future__ import annotations

import functools
import logging
import math
import re
import zoneinfo
from pathlib import Path
from typing import Self

import tzfpy
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from nocs.equipment.profiles import write_atomic

log = logging.getLogger(__name__)

FILE_NAME = "sites.json"
SITE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
EARTH_RADIUS_M = 6_371_000.0


class SiteModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HorizonPoint(SiteModel):
    azimuth: float = Field(ge=0, lt=360, description="Degrees from north through east.")
    altitude: float = Field(ge=-10, le=90, description="Lowest visible altitude, degrees.")


class Site(SiteModel):
    name: str = Field(default="", max_length=80)
    latitude: float = Field(ge=-90, le=90, description="Degrees, north positive.")
    longitude: float = Field(ge=-180, le=180, description="Degrees, east positive.")
    elevation: float = Field(default=0.0, description="Metres above sea level.")
    horizon: list[HorizonPoint] | None = Field(
        default=None,
        description="The local horizon (hills, trees, buildings): straight lines between "
        "points, all round the sky. None: a flat horizon at 0°.",
    )
    timezone: str | None = Field(
        default=None,
        max_length=64,
        description="IANA time zone the app shows the site's times in (America/Santiago); "
        "None: the one at its position (ADR 0052).",
    )

    @field_validator("timezone")
    @classmethod
    def _known_zone(cls, value: str | None) -> str | None:
        if value is not None and value not in known_zones():
            raise ValueError(f"unknown time zone {value!r}")
        return value

    @property
    def resolved_zone(self) -> str:
        """The time zone of the site's times: its own, else the one at its position."""
        return self.timezone or zone_at(self.latitude, self.longitude)

    @model_validator(mode="after")
    def _sorted_horizon(self) -> Self:
        if self.horizon is not None:
            if not self.horizon:
                raise ValueError("a horizon needs at least one point (or none at all)")
            self.horizon.sort(key=lambda point: point.azimuth)
            azimuths = [point.azimuth for point in self.horizon]
            if len(set(azimuths)) != len(azimuths):
                raise ValueError("the horizon has two points at the same azimuth")
        return self


class SiteFile(SiteModel):
    active: str | None = Field(default=None, description="The id of the active site.")
    sites: dict[str, Site] = Field(default_factory=dict[str, Site])

    @model_validator(mode="after")
    def _known_active(self) -> Self:
        for site_id in self.sites:
            if not SITE_ID.fullmatch(site_id):
                raise ValueError(f"invalid site id {site_id!r}")
        if self.active is not None and self.active not in self.sites:
            log.warning("the active site %r is not saved: none is active", self.active)
            self.active = None
        return self


class SiteStore:
    def __init__(self, config_dir: Path) -> None:
        self._path = config_dir / FILE_NAME

    def load(self) -> SiteFile:
        try:
            return SiteFile.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return SiteFile()
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return SiteFile()

    def save(self, sites: SiteFile) -> None:
        data = sites.model_dump_json(indent=2, exclude_none=True)
        write_atomic(self._path, data + "\n")


def distance(a: Site, latitude: float, longitude: float) -> float:
    """Metres on the ground from ``a`` to a position (haversine, a spherical Earth)."""
    phi1, phi2 = math.radians(a.latitude), math.radians(latitude)
    dphi = phi2 - phi1
    dlambda = math.radians(longitude - a.longitude)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def zone_at(latitude: float, longitude: float) -> str:
    """The IANA time zone at a position, from the bundled time zone map (no network).

    At sea, where no zone covers it, the nautical one (Etc/GMT+5 is UTC-5)."""
    name = tzfpy.get_tz(longitude, latitude)
    if name:
        return name
    hours = round(longitude / 15)
    return "Etc/UTC" if hours == 0 else f"Etc/GMT{-hours:+d}"


@functools.cache
def known_zones() -> frozenset[str]:
    """The time zones a site may name: the map's, the nautical ones and the system's."""
    nautical = {f"Etc/GMT{h:+d}" for h in range(-14, 13) if h} | {"Etc/UTC", "Etc/GMT"}
    return frozenset(tzfpy.timezonenames()) | nautical | zoneinfo.available_timezones()
