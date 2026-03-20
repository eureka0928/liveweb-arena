"""Open Meteo question templates"""

from .current_weather import OpenMeteoCurrentWeatherTemplate
from .comparison import OpenMeteoComparisonTemplate
from .hourly_extrema import OpenMeteoHourlyExtremaTemplate
from .forecast_trend import OpenMeteoForecastTrendTemplate
from .hourly_threshold import OpenMeteoHourlyThresholdTemplate
from .sunrise_sunset import OpenMeteoSunriseSunsetTemplate
from .hourly_time_of import OpenMeteoHourlyTimeOfTemplate

__all__ = [
    "OpenMeteoCurrentWeatherTemplate",
    "OpenMeteoComparisonTemplate",
    "OpenMeteoHourlyExtremaTemplate",
    "OpenMeteoForecastTrendTemplate",
    "OpenMeteoHourlyThresholdTemplate",
    "OpenMeteoSunriseSunsetTemplate",
    "OpenMeteoHourlyTimeOfTemplate",
]
