"""Environment readings over INDI's weather interface (``WEATHER_PARAMETERS``)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nocs.devices.base import Device, DeviceInterface
from nocs.indi.properties import NumberElement

# Magnus formula coefficients (Sonntag 1990), good to ±0.4 °C between -45 and 60 °C.
_MAGNUS_B = 17.62
_MAGNUS_C = 243.12


@dataclass(frozen=True, slots=True)
class Environment:
    temperature: float | None
    """°C"""
    humidity: float | None
    """Relative humidity, %"""
    dew_point: float | None
    """°C: the sensor's, or computed from temperature and humidity."""


def dew_point(temperature: float, humidity: float) -> float | None:
    if not 0 < humidity <= 100:
        return None
    gamma = math.log(humidity / 100) + _MAGNUS_B * temperature / (_MAGNUS_C + temperature)
    return _MAGNUS_C * gamma / (_MAGNUS_B - gamma)


class WeatherSensor(Device):
    INTERFACE = DeviceInterface.WEATHER
    REQUIRED = ("WEATHER_PARAMETERS",)

    @property
    def environment(self) -> Environment:
        prop = self.prop("WEATHER_PARAMETERS")

        def read(name: str) -> float | None:
            element = prop.elements.get(name)
            return element.value if isinstance(element, NumberElement) else None

        temperature = read("WEATHER_TEMPERATURE")
        humidity = read("WEATHER_HUMIDITY")
        dew = read("WEATHER_DEWPOINT")
        if dew is None and temperature is not None and humidity is not None:
            dew = dew_point(temperature, humidity)
        return Environment(temperature, humidity, dew)
