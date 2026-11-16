"""Fetches the forecast for the active site, as the active profile asks (ADR 0051).

State under ``("forecast",)``, None while the profile asks for none::

    {provider, fetched, attempted, error, hours}

The box asks the profile's provider for the active site's position, rounded to 0.1°
(about 10 km: enough for a forecast, and no closer to where the rig is). A forecast
is fetched again after ``REFRESH``; a failed attempt (no internet in the field, the
usual case) is tried again after ``RETRY``. The last forecast is kept on disk, so the
one fetched at home before leaving serves in the field: the state shows the hours
from the current one on while it is less than ``STALE`` old, and says when it was
fetched.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import anyio
import anyio.to_thread
from pydantic import ValidationError

from nocs.clock import Clock
from nocs.equipment.profiles import write_atomic
from nocs.forecast import openmeteo
from nocs.forecast.model import Forecast, ForecastHour, ForecastProvider
from nocs.sites import Site
from nocs.state import Json, StateStore

log = logging.getLogger(__name__)

ROOT = ("forecast",)
FILE_NAME = "forecast.json"
REFRESH = timedelta(hours=2)
RETRY = timedelta(minutes=10)
STALE = timedelta(hours=48)
CHECK = 30.0
"""Seconds between looks at the profile, the site and the clock."""

type Fetcher = Callable[[ForecastProvider, float, float], list[ForecastHour]]
"""Blocking: asks a provider for the hours at a rounded position."""


def fetch(provider: ForecastProvider, latitude: float, longitude: float) -> list[ForecastHour]:
    match provider:
        case "open-meteo":
            return openmeteo.fetch(latitude, longitude)


def rounded(site: Site) -> tuple[float, float]:
    """The position sent to a provider: 0.1°, about 10 km."""
    return round(site.latitude, 1), round(site.longitude, 1)


class ForecastService:
    def __init__(
        self,
        store: StateStore,
        data_dir: Path,
        clock: Clock,
        provider: Callable[[], ForecastProvider | None],
        site: Callable[[], Site | None],
        fetcher: Fetcher = fetch,
    ) -> None:
        self._store = store
        self._path = data_dir / FILE_NAME
        self._clock = clock
        self._provider = provider
        self._site = site
        self._fetcher = fetcher
        self._forecast = self._load()
        self._attempted: datetime | None = None
        self._error: str | None = None
        self._published: Json = None
        self._asked: tuple[ForecastProvider, float, float] | None = None
        """What the last attempt asked for: another provider or place starts afresh."""
        self._publish()

    async def run(self) -> None:
        """Keep the forecast current until cancelled."""
        while True:
            await self.update()
            await anyio.sleep(CHECK)

    async def update(self) -> None:
        """Fetch when due, then publish."""
        wanted = self._wanted()
        if wanted != self._asked:
            self._attempted, self._error = None, None
        if wanted is not None and self._due(wanted):
            self._asked = wanted
            provider, latitude, longitude = wanted
            self._attempted = self._clock.now()
            try:
                hours = await anyio.to_thread.run_sync(self._fetcher, provider, latitude, longitude)
            except (OSError, ValueError) as e:
                if self._error is None:
                    log.info("no forecast from %s: %s", provider, e)
                self._error = str(e) or type(e).__name__
            else:
                self._error = None
                self._forecast = Forecast(
                    provider=provider,
                    latitude=latitude,
                    longitude=longitude,
                    fetched=self._attempted.isoformat(timespec="seconds"),
                    hours=hours,
                )
                await anyio.to_thread.run_sync(self._save, self._forecast)
                log.info("forecast from %s: %d hours", provider, len(hours))
        self._publish()

    def _wanted(self) -> tuple[ForecastProvider, float, float] | None:
        provider, site = self._provider(), self._site()
        if provider is None or site is None:
            return None
        return provider, *rounded(site)

    def _due(self, wanted: tuple[ForecastProvider, float, float]) -> bool:
        now = self._clock.now()
        if self._attempted is not None and self._error is not None:
            return now - self._attempted >= RETRY
        current = self._current(wanted)
        if current is None:
            return self._attempted is None or now - self._attempted >= RETRY
        return now - datetime.fromisoformat(current.fetched) >= REFRESH

    def _current(self, wanted: tuple[ForecastProvider, float, float]) -> Forecast | None:
        """The kept forecast, if it is for this provider and position."""
        forecast = self._forecast
        if forecast is None:
            return None
        if (forecast.provider, forecast.latitude, forecast.longitude) != wanted:
            return None
        return forecast

    def _publish(self) -> None:
        wanted = self._wanted()
        state: Json = None
        if wanted is not None:
            forecast = self._current(wanted)
            now = self._clock.now()
            fresh = forecast is not None and now - datetime.fromisoformat(forecast.fetched) < STALE
            hour = now.replace(minute=0, second=0, microsecond=0)
            hours: list[Json] = (
                [
                    h.model_dump(mode="json")
                    for h in forecast.hours
                    if datetime.fromisoformat(h.time) >= hour
                ]
                if forecast is not None and fresh
                else []
            )
            state = {
                "provider": wanted[0],
                "fetched": forecast.fetched if forecast is not None else None,
                "attempted": (
                    self._attempted.isoformat(timespec="seconds") if self._attempted else None
                ),
                "error": self._error,
                "hours": hours,
            }
        if state != self._published:
            self._published = state
            self._store.set(ROOT, state)

    def _load(self) -> Forecast | None:
        try:
            return Forecast.model_validate_json(self._path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as e:
            log.warning("ignoring unreadable %s: %s", self._path, e)
            return None

    def _save(self, forecast: Forecast) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(self._path, forecast.model_dump_json() + "\n")
