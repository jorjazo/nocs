"""Tonight's weather forecast from an internet service the profile names (ADR 0051).

The service is in ``nocs.forecast.service``; the profile names a provider from
``nocs.forecast.model`` (kept free of NOCS imports for that).
"""

from nocs.forecast.model import PROVIDERS, Forecast, ForecastHour, ForecastProvider

__all__ = ["PROVIDERS", "Forecast", "ForecastHour", "ForecastProvider"]
