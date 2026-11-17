"""Open-Meteo's forecast API: free, without a key (https://open-meteo.com).

``fetch`` blocks (network): call it from a thread.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict

from nocs.forecast.model import ForecastHour

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 20.0
"""Seconds each step of the request (connecting, each read) may wait."""
MAX_SIZE = 2_000_000
"""Bytes of an answer at most (three days of hours are ~20 kB)."""
DAYS = 3
"""Days of hours asked for, from today's midnight UTC: tonight, wherever it is."""
VARIABLES = {
    "temperature": "temperature_2m",
    "humidity": "relative_humidity_2m",
    "precipitation": "precipitation",
    "precipitation_probability": "precipitation_probability",
    "cloud_cover": "cloud_cover",
    "cloud_low": "cloud_cover_low",
    "cloud_mid": "cloud_cover_mid",
    "cloud_high": "cloud_cover_high",
    "wind_speed": "wind_speed_10m",
    "wind_gusts": "wind_gusts_10m",
}


class _Hourly(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: list[int]


class _Response(BaseModel):
    hourly: _Hourly


def url(latitude: float, longitude: float) -> str:
    query = {
        "latitude": f"{latitude:.1f}",
        "longitude": f"{longitude:.1f}",
        "hourly": ",".join(VARIABLES.values()),
        "forecast_days": str(DAYS),
        "timeformat": "unixtime",
        "timezone": "GMT",
        "wind_speed_unit": "kmh",
    }
    return f"{URL}?{urllib.parse.urlencode(query)}"


def parse(data: bytes) -> list[ForecastHour]:
    """The hours of an answer; a variable it lacks is None."""
    hourly = _Response.model_validate_json(data).hourly
    extra = hourly.model_extra or {}
    columns: dict[str, list[object]] = {}
    for name, key in VARIABLES.items():
        values = extra.get(key)
        columns[name] = list(values) if isinstance(values, list) else []  # pyright: ignore[reportUnknownArgumentType]

    def value(name: str, i: int) -> float | None:
        column = columns[name]
        item = column[i] if i < len(column) else None
        return float(item) if isinstance(item, int | float) else None

    return [
        ForecastHour(
            time=datetime.fromtimestamp(t, UTC).isoformat(timespec="seconds"),
            **{name: value(name, i) for name in VARIABLES},
        )
        for i, t in enumerate(hourly.time)
    ]


def fetch(latitude: float, longitude: float) -> list[ForecastHour]:
    """Ask Open-Meteo; raises OSError (no network, an HTTP error), http.client's
    HTTPException (a broken answer), ValueError or OverflowError (not a forecast)."""
    request = urllib.request.Request(url(latitude, longitude), headers={"User-Agent": "nocs"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data: bytes = response.read(MAX_SIZE)
    try:
        return parse(data)
    except ValueError as e:
        raise ValueError("Open-Meteo's answer was not a forecast") from e
