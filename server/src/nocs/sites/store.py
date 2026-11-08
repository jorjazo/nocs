"""Saved sites and the active one, on disk (ADR 0038).

``<config dir>/sites.json`` holds every site the owner saved, by an id NOCS gives it,
and the id of the active one: sites belong to the box, not to equipment profiles.
"""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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
