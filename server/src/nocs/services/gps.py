"""A USB GPS through gpsd (ADR 0029): its fix, and its site for the active profile.

gpsd also feeds the GPS's time to chrony (a reference clock), which sets the system
clock; nocsd only reads positions, from gpsd's JSON stream (``?WATCH``, TPV reports).

State under ``("gps",)``::

    {connected, fix, latitude, longitude, elevation, time, site_differs}

``site_differs`` is whether a 3D fix is more than 0.01° or 50 m away from the active
profile's site, or the profile has none: the app then offers the GPS's site, which
is never applied without the owner asking. Positions are rounded and published at
most every ``PUBLISH`` seconds, since a fix wanders a little all the time.
"""

from __future__ import annotations

import json
import logging
import time
from typing import cast

import anyio
from anyio.streams.buffered import BufferedByteReceiveStream

from nocs.equipment.profiles import Site
from nocs.equipment.service import EquipmentService
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

ROOT = ("gps",)
RETRY = 10.0
"""Seconds between attempts to reach gpsd."""
PUBLISH = 10.0
"""Seconds between publications of a fix that keeps its quality."""
DEGREES = 0.01
METRES = 50.0
"""How far the GPS's site may be from the profile's before the app offers it."""
WATCH = b'?WATCH={"enable":true,"json":true};\n'


class NoFixError(Exception):
    """The GPS has no 3D fix to take a site from."""


class GpsService:
    def __init__(
        self, store: StateStore, equipment: EquipmentService, host: str, port: int
    ) -> None:
        self._store = store
        self._equipment = equipment
        self._host = host
        self._port = port
        self._connected = False
        self._fix: dict[str, object] | None = None
        """gpsd's last TPV report."""
        self._published: dict[str, Json] | None = None
        self._last_publish = 0.0
        equipment.add_listener(self._publish)
        self._publish()

    async def run(self) -> None:
        """Follow gpsd until cancelled, reconnecting when it goes away."""
        while True:
            try:
                async with await anyio.connect_tcp(self._host, self._port) as stream:
                    await stream.send(WATCH)
                    self._connected = True
                    self._publish()
                    receive = BufferedByteReceiveStream(stream)
                    while True:
                        self.on_message(await receive.receive_until(b"\n", 1 << 16))
            except (
                OSError,
                anyio.EndOfStream,
                anyio.IncompleteRead,
                anyio.DelimiterNotFound,
                anyio.BrokenResourceError,
            ) as e:
                if self._connected:
                    log.info("gpsd at %s:%s: %s", self._host, self._port, e)
            self._connected, self._fix = False, None
            self._publish()
            await anyio.sleep(RETRY)

    def on_message(self, line: bytes) -> None:
        """One line of gpsd's JSON stream; only TPV (time, position, velocity) counts."""
        try:
            message = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(message, dict):
            return
        report = cast(dict[str, object], message)
        if report.get("class") != "TPV":
            return
        previous = self._fix_name()
        self._fix = report
        self._publish(force=self._fix_name() != previous)

    def site(self) -> Site:
        """The GPS's position as a site, named as the profile's site is."""
        if self._fix_name() != "3d":
            raise NoFixError("the GPS has no 3D fix")
        latitude, longitude, elevation = self._position()
        if latitude is None or longitude is None:
            raise NoFixError("the GPS reports a 3D fix without a position")
        profile = self._equipment.active_profile
        name = profile.site.name if profile is not None and profile.site is not None else ""
        return Site(name=name or "GPS", latitude=latitude, longitude=longitude, elevation=elevation)

    def apply_site(self) -> Site:
        """Make the GPS's site the active profile's (ADR 0029: only when the owner asks)."""
        site = self.site()
        self._equipment.set_site(site)
        log.info("site of the active profile from the GPS: %s", site)
        return site

    def _fix_name(self) -> str:
        mode = self._fix.get("mode") if self._fix is not None else None
        return {2: "2d", 3: "3d"}.get(mode, "none") if isinstance(mode, int) else "none"

    def _position(self) -> tuple[float | None, float | None, float]:
        fix = self._fix or {}

        def number(key: str) -> float | None:
            value = fix.get(key)
            return float(value) if isinstance(value, int | float) else None

        elevation = number("altMSL")
        if elevation is None:
            elevation = number("alt")
        return number("lat"), number("lon"), elevation if elevation is not None else 0.0

    def _differs(self) -> bool | None:
        if self._fix_name() != "3d":
            return None
        profile = self._equipment.active_profile
        if profile is None:
            return None
        site = profile.site
        latitude, longitude, elevation = self._position()
        if site is None or latitude is None or longitude is None:
            return True
        return (
            abs(site.latitude - latitude) > DEGREES
            or abs((site.longitude - longitude + 180) % 360 - 180) > DEGREES
            or abs(site.elevation - elevation) > METRES
        )

    def _publish(self, force: bool = False) -> None:
        fix = self._fix_name()
        latitude, longitude, elevation = self._position()
        when = self._fix.get("time") if self._fix is not None else None
        state: dict[str, Json] = {
            "connected": self._connected,
            "fix": fix,
            "latitude": None if fix == "none" or latitude is None else round(latitude, 4),
            "longitude": None if fix == "none" or longitude is None else round(longitude, 4),
            "elevation": round(elevation) if fix == "3d" else None,
            "time": when if isinstance(when, str) else None,
            "site_differs": self._differs(),
        }
        previous = self._published
        if previous is not None and not force:
            changed = any(state[k] != previous[k] for k in ("connected", "fix", "site_differs"))
            moved = any(state[k] != previous[k] for k in ("latitude", "longitude", "elevation"))
            if not changed and (not moved or time.monotonic() - self._last_publish < PUBLISH):
                return
        self._published, self._last_publish = state, time.monotonic()
        self._store.set(ROOT, state)
