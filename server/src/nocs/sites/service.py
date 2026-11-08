"""The saved sites and the active one: the state, and what follows the active site.

State under ``("sites",)``::

    {active, saved: {<id>: {name, latitude, longitude, elevation, horizon}}}

The box has one active site or none (ADR 0038); everything that needs the site (the
sky, flats, the mount, polar alignment, sequences, FITS headers and the catalog) reads
it from here. The active site neither changes nor is edited while a job holds the
mount: a go to, a sequence, polar alignment or sky flats computed from one site would
be wrong for another (``check``, which raises when it is held).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from nocs.devices import Location
from nocs.sites.store import HorizonPoint, Site, SiteFile, SiteStore, distance
from nocs.state import Path, StateStore

log = logging.getLogger(__name__)

ROOT: Path = ("sites",)
NEAR = 500.0
"""Metres on the ground within which a position is at a saved site (a GPS fix)."""


class SiteError(Exception):
    """No such site."""


class SiteService:
    def __init__(
        self, store: StateStore, sites: SiteStore, check: Callable[[], None] = lambda: None
    ) -> None:
        self._store = store
        self._sites = sites
        self._check = check
        self._file = sites.load()
        self._listeners: list[Callable[[], None]] = []
        self._saved_listeners: list[Callable[[], None]] = []
        self._publish()

    @property
    def active_id(self) -> str | None:
        return self._file.active

    @property
    def active(self) -> Site | None:
        return self._file.sites[self._file.active] if self._file.active is not None else None

    def location(self) -> Location | None:
        """The active site as a location, for the sky and the mount."""
        site = self.active
        return Location(site.latitude, site.longitude, site.elevation) if site else None

    def longitude(self) -> float | None:
        site = self.active
        return site.longitude if site else None

    def horizon(self) -> list[HorizonPoint] | None:
        site = self.active
        return site.horizon if site else None

    def saved(self) -> dict[str, Site]:
        return dict(self._file.sites)

    def get(self, site_id: str) -> Site:
        try:
            return self._file.sites[site_id]
        except KeyError:
            raise SiteError(f"no site {site_id}") from None

    def add(self, site: Site, *, activate: bool = False) -> str:
        """Save a new site; returns its id."""
        if activate:
            self._check()
        site_id = uuid.uuid4().hex[:8]
        sites = {**self._file.sites, site_id: site}
        self._save(SiteFile(active=site_id if activate else self._file.active, sites=sites))
        log.info("site %s saved: %s", site_id, site)
        return site_id

    def put(self, site_id: str, site: Site) -> None:
        """Change a saved site; the active one only while no job holds the mount."""
        self.get(site_id)
        if site_id == self._file.active:
            self._check()
        self._save(SiteFile(active=self._file.active, sites={**self._file.sites, site_id: site}))

    def delete(self, site_id: str) -> None:
        """Forget a site; deleting the active one leaves the box with none."""
        self.get(site_id)
        if site_id == self._file.active:
            self._check()
        sites = {k: v for k, v in self._file.sites.items() if k != site_id}
        active = None if site_id == self._file.active else self._file.active
        self._save(SiteFile(active=active, sites=sites))

    def activate(self, site_id: str | None) -> None:
        """Make a saved site the active one (or none), while no job holds the mount."""
        if site_id is not None:
            self.get(site_id)
        if site_id == self._file.active:
            return
        self._check()
        self._save(SiteFile(active=site_id, sites=self._file.sites))
        log.info("active site: %s", site_id)

    def nearest(self, latitude: float, longitude: float, within: float = NEAR) -> str | None:
        """The saved site nearest to a position, if one is within ``within`` metres."""
        near = [
            (d, site_id)
            for site_id, site in self._file.sites.items()
            if (d := distance(site, latitude, longitude)) <= within
        ]
        return min(near)[1] if near else None

    def add_listener(
        self, listener: Callable[[], None], *, saved: bool = False
    ) -> Callable[[], None]:
        """Call ``listener`` whenever the active site changes (another one, or edited), or
        with ``saved`` whenever any saved site does."""
        listeners = self._saved_listeners if saved else self._listeners
        listeners.append(listener)
        return lambda: listeners.remove(listener)

    def _save(self, sites: SiteFile) -> None:
        before = self.active
        self._sites.save(sites)
        self._file = sites
        self._publish()
        changed = self.active != before
        for listener in [*(self._listeners if changed else []), *self._saved_listeners]:
            listener()

    def _publish(self) -> None:
        self._store.set(
            ROOT,
            {
                "active": self._file.active,
                "saved": {k: v.model_dump(mode="json") for k, v in self._file.sites.items()},
            },
        )
