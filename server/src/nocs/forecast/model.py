"""A forecast as NOCS keeps it: hour by hour, in UTC, and where and when it came from."""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

type ForecastProvider = Literal["open-meteo"]
"""Services NOCS gets forecasts from; more (some with an API key) may follow."""

PROVIDERS: tuple[ForecastProvider, ...] = get_args(ForecastProvider.__value__)


class ForecastModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ForecastHour(ForecastModel):
    time: str = Field(description="UTC, the start of the hour.")
    temperature: float | None = Field(description="°C at 2 m.")
    humidity: float | None = Field(description="Relative humidity at 2 m, %.")
    precipitation: float | None = Field(description="mm in the hour.")
    precipitation_probability: float | None = Field(description="%.")
    cloud_cover: float | None = Field(description="% of the sky.")
    cloud_low: float | None = Field(description="% of the sky, low clouds (up to 3 km).")
    cloud_mid: float | None = Field(description="% of the sky, mid clouds (3 to 8 km).")
    cloud_high: float | None = Field(description="% of the sky, high clouds (above 8 km).")
    wind_speed: float | None = Field(description="km/h at 10 m.")
    wind_gusts: float | None = Field(description="km/h at 10 m.")


class Forecast(ForecastModel):
    """What a provider said, kept on disk so that one fetched at home serves in the field."""

    provider: ForecastProvider
    latitude: float = Field(description="As sent: rounded to 0.1°.")
    longitude: float = Field(description="As sent: rounded to 0.1°.")
    fetched: str = Field(description="UTC.")
    hours: list[ForecastHour]
