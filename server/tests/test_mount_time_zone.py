"""The mount's local time follows the active site's time zone (ADR 0052)."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from nocs.clock import Clock
from nocs.jobs import JobManager
from nocs.mount.service import MountService
from nocs.sites import Site
from nocs.state import StateStore

SANTIAGO = Site(name="Santiago", latitude=-33.5, longitude=-70.55, elevation=600)


class _Sites:
    """Stands in for the bridge, the equipment and the sites: no mount, no listeners."""

    client = None

    def __init__(self, site: Site | None) -> None:
        self.active = site

    def watch(self, listener: Callable[..., None]) -> Callable[[], None]:
        return lambda: None

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        return lambda: None

    def location(self) -> None:
        return None


def offset(site: Site | None, when: datetime, client: float | None) -> float:
    store = StateStore()
    clock = Clock(store, system=lambda: when)
    if client is not None:
        clock.report(when, client)
    stub = cast(Any, _Sites(site))
    mount = MountService(store, JobManager(store), stub, stub, clock, stub)
    return mount._utc_offset(when)  # pyright: ignore[reportPrivateUsage]


def test_the_site_s_zone_with_its_summer_time() -> None:
    summer, winter = datetime(2026, 11, 15, 3, tzinfo=UTC), datetime(2026, 7, 15, 3, tzinfo=UTC)
    # The client's own zone does not matter while a site is active.
    assert offset(SANTIAGO, summer, client=2) == -3
    assert offset(SANTIAGO, winter, client=2) == -4
    madrid = SANTIAGO.model_copy(update={"timezone": "Europe/Madrid"})
    assert offset(madrid, winter, client=None) == 2


def test_without_a_site_the_client_s_zone() -> None:
    when = datetime(2026, 11, 15, 3, tzinfo=UTC)
    assert offset(None, when, client=-5) == -5
    assert offset(None, when, client=None) == 0
