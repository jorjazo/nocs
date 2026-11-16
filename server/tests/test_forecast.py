"""Tonight's forecast: when it is fetched, kept and shown (ADR 0051)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nocs.api.schemas import ForecastState
from nocs.clock import Clock
from nocs.forecast import ForecastHour, ForecastProvider, openmeteo
from nocs.forecast.service import ForecastService
from nocs.sites import Site
from nocs.state import StateStore

DIAGUITAS = Site(name="Diaguitas", latitude=-30.0277, longitude=-70.6733, elevation=700)
START = datetime(2026, 11, 15, 21, 40, tzinfo=UTC)


def hours(start: datetime, count: int = 72) -> list[ForecastHour]:
    first = start.replace(minute=0, second=0, microsecond=0)
    return [
        ForecastHour(
            time=(first + timedelta(hours=i)).isoformat(timespec="seconds"),
            temperature=15.0 - i / 10,
            humidity=60.0,
            precipitation=0.0,
            precipitation_probability=5.0,
            cloud_cover=10.0,
            cloud_low=0.0,
            cloud_mid=5.0,
            cloud_high=10.0,
            wind_speed=8.0,
            wind_gusts=20.0,
        )
        for i in range(count)
    ]


class Rig:
    def __init__(self, data: Path, provider: ForecastProvider | None = "open-meteo") -> None:
        self.now = START
        self.provider: ForecastProvider | None = provider
        self.site: Site | None = DIAGUITAS
        self.asked: list[tuple[str, float, float]] = []
        self.offline = False
        self.store = StateStore()
        self.service = ForecastService(
            self.store,
            data,
            Clock(self.store, system=lambda: self.now),
            provider=lambda: self.provider,
            site=lambda: self.site,
            fetcher=self.fetch,
        )

    def fetch(
        self, provider: ForecastProvider, latitude: float, longitude: float
    ) -> list[ForecastHour]:
        self.asked.append((provider, latitude, longitude))
        if self.offline:
            raise OSError("no route to host")
        return hours(self.now)

    def state(self) -> ForecastState | None:
        value = self.store.get(("forecast",))
        return None if value is None else ForecastState.model_validate(value)

    async def at(self, delta: timedelta) -> ForecastState | None:
        self.now += delta
        await self.service.update()
        return self.state()


async def test_no_provider_no_forecast(tmp_path: Path) -> None:
    rig = Rig(tmp_path, provider=None)
    assert await rig.at(timedelta()) is None
    rig.provider, rig.site = "open-meteo", None
    assert await rig.at(timedelta()) is None
    assert rig.asked == []


async def test_fetched_for_the_rounded_site_and_again_two_hours_later(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    state = await rig.at(timedelta())
    assert rig.asked == [("open-meteo", -30.0, -70.7)]
    assert state is not None
    assert (state.fetched, state.error) == (START.isoformat(timespec="seconds"), None)
    assert state.hours[0].time == "2026-11-15T21:00:00+00:00"  # from the current hour on
    state = await rig.at(timedelta(minutes=90))
    assert state is not None
    assert state.hours[0].time == "2026-11-15T23:00:00+00:00"
    assert len(rig.asked) == 1
    await rig.at(timedelta(minutes=30))
    assert len(rig.asked) == 2
    # A few hundred metres away: the same rounded position, nothing to fetch.
    rig.site = DIAGUITAS.model_copy(update={"latitude": -30.03})
    await rig.at(timedelta(minutes=1))
    assert len(rig.asked) == 2
    # Another site: fetched at once.
    rig.site = DIAGUITAS.model_copy(update={"latitude": -33.45, "longitude": -70.66})
    state = await rig.at(timedelta(minutes=1))
    assert rig.asked[-1] == ("open-meteo", -33.5, -70.7)


async def test_offline_it_keeps_the_last_and_tries_every_ten_minutes(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.at(timedelta())
    rig.offline = True
    state = await rig.at(timedelta(hours=3))
    assert state is not None
    assert state.error == "no route to host"
    assert state.fetched == START.isoformat(timespec="seconds")
    assert state.hours  # the last one still serves
    await rig.at(timedelta(minutes=5))
    assert len(rig.asked) == 2
    await rig.at(timedelta(minutes=5))
    assert len(rig.asked) == 3
    rig.offline = False
    state = await rig.at(timedelta(minutes=10))
    assert state is not None
    assert state.error is None
    assert state.fetched == rig.now.isoformat(timespec="seconds")


async def test_the_one_fetched_at_home_serves_in_the_field(tmp_path: Path) -> None:
    home = Rig(tmp_path)
    await home.at(timedelta())
    field = Rig(tmp_path)  # nocsd starts again, offline
    field.offline = True
    state = await field.at(timedelta(hours=5))
    assert state is not None
    assert state.error == "no route to host"
    assert state.fetched == START.isoformat(timespec="seconds")
    assert state.hours[0].time == "2026-11-16T02:00:00+00:00"
    # Two days later it says nothing any more, but when it was fetched.
    state = await field.at(timedelta(hours=44))
    assert state is not None
    assert (state.hours, state.fetched) == ([], START.isoformat(timespec="seconds"))


def test_open_meteo_s_answer() -> None:
    answer = {
        "latitude": -30.05,
        "hourly_units": {"time": "unixtime"},
        "hourly": {
            "time": [1794787200, 1794790800],
            "temperature_2m": [17.0, 16.2],
            "relative_humidity_2m": [70, 72],
            "precipitation": [0.0, 0.1],
            "precipitation_probability": [0, 10],
            "cloud_cover": [98, None],
            "cloud_cover_low": [0, 0],
            "cloud_cover_mid": [16, 20],
            "cloud_cover_high": [98, 90],
            "wind_speed_10m": [4.7, 6],
            "wind_gusts_10m": [15.5, 18.0],
        },
    }
    first, second = openmeteo.parse(json.dumps(answer).encode())
    assert first.time == "2026-11-16T00:00:00+00:00"
    assert (first.temperature, first.humidity, first.cloud_high, first.wind_gusts) == (
        17.0,
        70.0,
        98.0,
        15.5,
    )
    assert (second.cloud_cover, second.precipitation) == (None, 0.1)
    with pytest.raises(ValueError, match="hourly"):
        openmeteo.parse(b'{"error": true, "reason": "bad latitude"}')


def test_open_meteo_gets_the_rounded_position_only() -> None:
    url = openmeteo.url(-30.0, -70.7)
    assert "latitude=-30.0&longitude=-70.7" in url
    assert "cloud_cover_low" in url
