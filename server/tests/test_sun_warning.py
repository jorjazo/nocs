"""The Sun's warning in the mount service: how long its acknowledgment lasts (ADR 0049)."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from nocs.clock import Clock
from nocs.devices import Location
from nocs.jobs import JobManager
from nocs.mount.service import MountService
from nocs.state import StateStore

SANTIAGO = Location(-33.5, -70.55, 600.0)
"""Local mean midnight there is 04:42 UTC."""


class _Listeners:
    """Stands in for the bridge, the equipment and the sites: no mount, no listeners."""

    client = None

    def __init__(self, site: Location | None) -> None:
        self.site = site

    def watch(self, listener: Callable[..., None]) -> Callable[[], None]:
        return lambda: None

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        return lambda: None

    def location(self) -> Location | None:
        return self.site


class _Rig:
    def __init__(self, now: datetime, site: Location | None = SANTIAGO) -> None:
        self.now = now
        self.sites = _Listeners(site)
        store = StateStore()
        stub = cast(Any, self.sites)
        self.mount = MountService(
            store, JobManager(store), stub, stub, Clock(store, system=lambda: self.now), stub
        )


def test_the_acknowledgment_lasts_until_the_site_s_midnight() -> None:
    rig = _Rig(datetime(2026, 11, 15, 18, 0, tzinfo=UTC))
    assert not rig.mount.sun_acknowledged
    rig.mount.acknowledge_sun()
    assert rig.mount.sun_acknowledged
    rig.now = datetime(2026, 11, 16, 4, 30, tzinfo=UTC)  # 23:48 at the site
    assert rig.mount.sun_acknowledged
    rig.now = datetime(2026, 11, 16, 4, 50, tzinfo=UTC)  # past midnight there
    assert not rig.mount.sun_acknowledged


def test_an_acknowledgment_before_the_site_is_chosen() -> None:
    # Acknowledged at 02:00 UTC with no site: still the 14th at the site, chosen later.
    rig = _Rig(datetime(2026, 11, 15, 2, 0, tzinfo=UTC), site=None)
    rig.mount.acknowledge_sun()
    rig.sites.site = SANTIAGO
    assert rig.mount.sun_acknowledged
    rig.now += timedelta(hours=3)  # 00:18 of the 15th at the site
    assert not rig.mount.sun_acknowledged
