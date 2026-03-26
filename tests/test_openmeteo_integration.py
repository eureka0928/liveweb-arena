"""Focused tests for the Open Meteo plugin and templates."""

import asyncio

import pytest

from liveweb_arena.core.cache import normalize_url
from liveweb_arena.core.gt_collector import GTCollector, GTSourceType, set_current_gt_collector
from liveweb_arena.core.task_registry import TaskRegistry
from liveweb_arena.core.validators.base import get_registered_templates
from liveweb_arena.plugins import get_all_plugins
from liveweb_arena.plugins.base import SubTask
from liveweb_arena.plugins.openmeteo.openmeteo import OpenMeteoPlugin
from liveweb_arena.plugins.openmeteo.templates.common import DOCS_HOME_URL
from liveweb_arena.plugins.openmeteo.templates.comparison import OpenMeteoComparisonTemplate
from liveweb_arena.plugins.openmeteo.templates.current_weather import OpenMeteoCurrentWeatherTemplate
from liveweb_arena.plugins.openmeteo.templates.forecast_trend import OpenMeteoForecastTrendTemplate
from liveweb_arena.plugins.openmeteo.templates.hourly_extrema import OpenMeteoHourlyExtremaTemplate
from liveweb_arena.plugins.openmeteo.templates.hourly_threshold import OpenMeteoHourlyThresholdTemplate
from liveweb_arena.plugins.openmeteo.templates.sunrise_sunset import OpenMeteoSunriseSunsetTemplate
from liveweb_arena.plugins.openmeteo.templates.hourly_time_of import OpenMeteoHourlyTimeOfTemplate
from liveweb_arena.plugins.openmeteo.templates.variables import CITIES


@pytest.fixture
def collector():
    gt_collector = GTCollector(
        subtasks=[SubTask(plugin_name="openmeteo", intent="test", validation_info={}, answer_tag="answer1")]
    )
    set_current_gt_collector(gt_collector)
    try:
        yield gt_collector
    finally:
        set_current_gt_collector(None)


def run_async(coro):
    return asyncio.run(coro)


def test_plugin_and_templates_registered():
    assert "openmeteo" in get_all_plugins()
    templates = get_registered_templates()
    for name in [
        "openmeteo_current",
        "openmeteo_comparison",
        "openmeteo_hourly_extrema",
        "openmeteo_forecast_trend",
        "openmeteo_hourly_threshold",
        "openmeteo_sunrise_sunset",
        "openmeteo_hourly_time_of",
    ]:
        assert name in templates


def test_coordinate_extraction_and_cache_keys():
    plugin = OpenMeteoPlugin()

    lat, lon = plugin._extract_coords(
        "https://open-meteo.com/en/docs#latitude=35.68&longitude=139.65&current=temperature_2m"
    )
    assert lat == 35.68
    assert lon == 139.65

    lat, lon = plugin._extract_coords(
        "https://open-meteo.com/en/docs?latitude=40.71&longitude=-74.01"
    )
    assert abs(lat - 40.71) < 0.001
    assert abs(lon - (-74.01)) < 0.001

    city1_url = "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65#latitude=35.68&longitude=139.65"
    city2_url = "https://open-meteo.com/en/docs?latitude=51.51&longitude=-0.13#latitude=51.51&longitude=-0.13"
    assert normalize_url(city1_url) != normalize_url(city2_url)


@pytest.mark.parametrize(
    ("template_cls", "expected_fields"),
    [
        (OpenMeteoCurrentWeatherTemplate, {"city_name", "coord_key", "metric_field", "unit"}),
        (OpenMeteoHourlyExtremaTemplate, {"city_name", "coord_key", "is_max"}),
        (OpenMeteoForecastTrendTemplate, {"city_name", "coord_key"}),
        (OpenMeteoHourlyThresholdTemplate, {"city_name", "coord_key", "threshold", "is_above"}),
        (OpenMeteoSunriseSunsetTemplate, {"city_name", "coord_key", "day_idx"}),
        (OpenMeteoHourlyTimeOfTemplate, {"city_name", "coord_key", "is_max"}),
    ],
)
def test_interaction_first_templates_start_from_generic_docs(template_cls, expected_fields):
    question = template_cls().generate(42)
    assert question.start_url == DOCS_HOME_URL
    assert expected_fields.issubset(question.validation_info)
    assert question.expected_steps >= 6


def test_comparison_template_remains_city_specific():
    question = OpenMeteoComparisonTemplate().generate(42)
    assert question.start_url != DOCS_HOME_URL
    assert "latitude=" in question.start_url
    assert "city2_coord_key" in question.validation_info
    # Verify question asks for numeric difference, not binary choice
    assert "difference" in question.question_text.lower() or "degrees" in question.question_text.lower()


def test_current_weather_requires_city_visit():
    result = run_async(
        OpenMeteoCurrentWeatherTemplate().get_ground_truth(
            {
                "city_name": "Tokyo",
                "coord_key": "35.68,139.65",
                "metric_field": "temperature",
                "unit": "°C",
            }
        )
    )
    assert result.success is False
    assert result.is_data_not_collected()


def test_gt_collector_merges_openmeteo_pages(collector):
    fake_api_data = {
        "_location_key": "35.68,139.65",
        "current_weather": {"temperature": 12.5},
        "hourly": {"time": ["2026-03-17T00:00"], "temperature_2m": [12.5]},
        "daily": {"time": ["2026-03-17"], "temperature_2m_max": [16.0], "temperature_2m_min": [9.0]},
    }

    result = collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        fake_api_data,
    )
    assert "weather[35.68,139.65]" in result
    assert "openmeteo:35.68,139.65" in collector.get_collected_api_data()


def test_hourly_extrema_uses_hourly_series_not_daily_summary(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5, "time": "2026-03-17T09:00"},
            "daily": {
                "time": ["2026-03-17", "2026-03-18"],
                "temperature_2m_max": [99.0, 50.0],
                "temperature_2m_min": [-99.0, 0.0],
            },
            "hourly": {
                "time": [
                    "2026-03-17T00:00",
                    "2026-03-17T06:00",
                    "2026-03-17T12:00",
                    "2026-03-18T00:00",
                ],
                "temperature_2m": [8.0, 11.5, 14.0, 3.0],
            },
        },
    )

    tmpl = OpenMeteoHourlyExtremaTemplate()
    max_result = run_async(
        tmpl.get_ground_truth({"city_name": "Tokyo", "coord_key": "35.68,139.65", "is_max": True})
    )
    min_result = run_async(
        tmpl.get_ground_truth({"city_name": "Tokyo", "coord_key": "35.68,139.65", "is_max": False})
    )

    assert max_result.success is True
    assert max_result.value == "14.0°C"
    assert min_result.success is True
    assert min_result.value == "8.0°C"


def test_forecast_trend_uses_daily_values_after_city_visit(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5, "time": "2026-03-17T09:00"},
            "daily": {
                "time": ["2026-03-17", "2026-03-18"],
                "temperature_2m_max": [15.2, 13.8],
            },
            "hourly": {
                "time": ["2026-03-17T00:00", "2026-03-17T06:00"],
                "temperature_2m": [8.0, 11.5],
            },
        },
    )

    result = run_async(
        OpenMeteoForecastTrendTemplate().get_ground_truth(
            {
                "city_name": "Tokyo",
                "coord_key": "35.68,139.65",
                "metric_field": "temperature_2m_max",
                "metric_label": "daily maximum temperature",
                "unit": "°C",
                "day1_idx": 0,
                "day2_idx": 1,
                "day1_label": "today",
                "day2_label": "tomorrow",
            }
        )
    )
    assert result.success is True
    assert "1.4" in result.value
    assert "Lower" in result.value or "lower" in result.value


def test_comparison_gt_returns_numeric_difference(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5},
        },
    )
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=51.51&longitude=-0.13",
        {
            "_location_key": "51.51,-0.13",
            "current_weather": {"temperature": 8.3},
        },
    )

    result = run_async(
        OpenMeteoComparisonTemplate().get_ground_truth(
            {
                "city1_name": "Tokyo",
                "city1_coord_key": "35.68,139.65",
                "city2_name": "London",
                "city2_coord_key": "51.51,-0.13",
            }
        )
    )
    assert result.success is True
    assert result.value == "4.2°C"  # 12.5 - 8.3 = 4.2


def test_registry_contains_openmeteo_templates():
    expected = {
        85: ("openmeteo", "openmeteo_current"),
        86: ("openmeteo", "openmeteo_comparison"),
        87: ("openmeteo", "openmeteo_hourly_extrema"),
        88: ("openmeteo", "openmeteo_forecast_trend"),
        99: ("openmeteo", "openmeteo_hourly_threshold"),
        100: ("openmeteo", "openmeteo_sunrise_sunset"),
        101: ("openmeteo", "openmeteo_hourly_time_of"),
    }
    for template_id, template_info in expected.items():
        assert TaskRegistry.TEMPLATES[template_id] == template_info

    TaskRegistry._ensure_initialized()
    assert (85,) in TaskRegistry._combinations
    assert (99,) in TaskRegistry._combinations


def test_city_docs_urls_are_unique_and_parseable():
    plugin = OpenMeteoPlugin()
    seen = set()
    for city in CITIES:
        normalized = normalize_url(city.docs_url())
        assert normalized not in seen
        seen.add(normalized)

        lat, lon = plugin._extract_coords(city.docs_url())
        assert lat is not None
        assert lon is not None


def test_openmeteo_templates_expose_page_only_gt_source():
    assert OpenMeteoCurrentWeatherTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoComparisonTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoHourlyExtremaTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoForecastTrendTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoHourlyThresholdTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoSunriseSunsetTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert OpenMeteoHourlyTimeOfTemplate().get_gt_source() == GTSourceType.PAGE_ONLY


def test_hourly_threshold_counts_correctly(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5, "time": "2026-03-17T09:00"},
            "daily": {"time": ["2026-03-17"]},
            "hourly": {
                "time": [
                    "2026-03-17T00:00",
                    "2026-03-17T06:00",
                    "2026-03-17T12:00",
                    "2026-03-17T18:00",
                ],
                "temperature_2m": [5.0, 10.0, 20.0, 15.0],
            },
        },
    )

    tmpl = OpenMeteoHourlyThresholdTemplate()

    # Above 10: 20.0, 15.0 → 2
    result_above = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "metric_field": "temperature_2m", "threshold": 10.0, "is_above": True,
        })
    )
    assert result_above.success is True
    assert result_above.value == "2"

    # Below 10: 5.0 → 1
    result_below = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "metric_field": "temperature_2m", "threshold": 10.0, "is_above": False,
        })
    )
    assert result_below.success is True
    assert result_below.value == "1"


def test_hourly_threshold_uses_jittered_thresholds():
    """Verify that different seeds produce different (non-round) thresholds."""
    tmpl = OpenMeteoHourlyThresholdTemplate()
    thresholds = set()
    for seed in range(50):
        q = tmpl.generate(seed)
        thresholds.add(q.validation_info["threshold"])
    # With jitter, we should get many distinct values (not just the base list)
    assert len(thresholds) > 20


def test_daylight_duration_computes_correctly(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5, "time": "2026-03-17T09:00"},
            "daily": {
                "time": ["2026-03-17", "2026-03-18", "2026-03-19"],
                "sunrise": ["2026-03-17T06:03", "2026-03-18T05:58", "2026-03-19T05:56"],
                "sunset": ["2026-03-17T18:05", "2026-03-18T18:06", "2026-03-19T18:07"],
            },
        },
    )

    tmpl = OpenMeteoSunriseSunsetTemplate()

    # Day 0: 06:03 → 18:05 = 12h 2m
    result = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "day_idx": 0, "day_label": "today",
        })
    )
    assert result.success is True
    assert result.value == "12h 2m"

    # Day 1: 05:58 → 18:06 = 12h 8m
    result_d1 = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "day_idx": 1, "day_label": "tomorrow",
        })
    )
    assert result_d1.success is True
    assert result_d1.value == "12h 8m"


def test_daylight_duration_handles_null_polar(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=68.97&longitude=33.09",
        {
            "_location_key": "68.97,33.09",
            "current_weather": {"temperature": -5.0, "time": "2026-06-21T12:00"},
            "daily": {
                "time": ["2026-06-21"],
                "sunrise": [None],
                "sunset": [None],
            },
        },
    )

    result = run_async(
        OpenMeteoSunriseSunsetTemplate().get_ground_truth({
            "city_name": "Murmansk", "coord_key": "68.97,33.09",
            "day_idx": 0, "day_label": "today",
        })
    )
    assert result.success is False


def test_hourly_time_of_finds_extremum_time(collector):
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        {
            "_location_key": "35.68,139.65",
            "current_weather": {"temperature": 12.5, "time": "2026-03-17T09:00"},
            "daily": {"time": ["2026-03-17"]},
            "hourly": {
                "time": [
                    "2026-03-17T00:00",
                    "2026-03-17T06:00",
                    "2026-03-17T12:00",
                    "2026-03-17T14:00",
                    "2026-03-17T18:00",
                ],
                "wind_speed_10m": [5.0, 12.0, 8.0, 12.0, 3.0],
            },
        },
    )

    tmpl = OpenMeteoHourlyTimeOfTemplate()

    # Max wind = 12.0 at 06:00 (first occurrence wins over 14:00)
    max_result = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "is_max": True, "metric_field": "wind_speed_10m",
        })
    )
    assert max_result.success is True
    assert max_result.value == "06:00"

    # Min wind = 3.0 at 18:00
    min_result = run_async(
        tmpl.get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "is_max": False, "metric_field": "wind_speed_10m",
        })
    )
    assert min_result.success is True
    assert min_result.value == "18:00"


def test_hourly_time_of_excludes_temperature():
    """Template 101 must not generate temperature questions (diurnal cycle is a fixed pattern)."""
    tmpl = OpenMeteoHourlyTimeOfTemplate()
    for seed in range(100):
        q = tmpl.generate(seed)
        assert q.validation_info["metric_field"] != "temperature_2m", (
            f"seed {seed} generated temperature question — should be excluded"
        )


def test_hourly_time_of_rejects_degenerate_all_same(collector):
    """All-zero precip (arid cities) must fail GT, not return 00:00."""
    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=33.45&longitude=-112.07",
        {
            "_location_key": "33.45,-112.07",
            "current_weather": {"temperature": 35.0, "time": "2026-03-17T12:00"},
            "daily": {"time": ["2026-03-17"]},
            "hourly": {
                "time": [f"2026-03-17T{h:02d}:00" for h in range(24)],
                "precipitation_probability": [0] * 24,
            },
        },
    )

    result = run_async(
        OpenMeteoHourlyTimeOfTemplate().get_ground_truth({
            "city_name": "Phoenix", "coord_key": "33.45,-112.07",
            "is_max": True, "metric_field": "precipitation_probability",
        })
    )
    assert result.success is False


def test_hourly_threshold_requires_city_visit():
    result = run_async(
        OpenMeteoHourlyThresholdTemplate().get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "metric_field": "temperature_2m", "threshold": 20.0, "is_above": True,
        })
    )
    assert result.success is False
    assert result.is_data_not_collected()


def test_gt_with_real_api_data(collector):
    """Verify GT returns concrete values using real Open-Meteo API data (Tokyo, 2026-03-26)."""
    # Real API response snapshot — fetched from:
    # https://api.open-meteo.com/v1/forecast?latitude=35.68&longitude=139.65
    #   &current_weather=true&hourly=temperature_2m,relative_humidity_2m,
    #   wind_speed_10m,precipitation_probability
    #   &daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,
    #   sunrise,sunset&timezone=auto&forecast_days=3
    real_data = {
        "_location_key": "35.68,139.65",
        "current_weather": {"time": "2026-03-26T17:00", "temperature": 11.3, "windspeed": 5.1, "winddirection": 352},
        "hourly": {
            "time": [f"2026-03-26T{h:02d}:00" for h in range(24)] + [f"2026-03-27T{h:02d}:00" for h in range(24)],
            "temperature_2m": [8.4,8.1,8.0,8.6,8.5,8.2,8.5,8.6,8.8,10.1,10.4,10.8,11.7,11.8,11.5,11.2,11.5,11.3,10.8,10.5,10.1,10.0,9.9,9.8,
                               9.7,9.5,9.3,9.1,8.8,8.6,8.4,8.8,9.7,10.9,12.3,13.5,14.9,15.9,16.3,16.5,16.1,15.3,14.3,12.8,11.8,11.2,10.9,10.7],
            "relative_humidity_2m": [99,99,99,98,98,98,98,98,98,96,95,94,92,92,91,92,90,90,93,92,95,96,97,96,
                                     93,93,93,93,94,95,94,91,86,81,76,73,67,61,57,56,59,64,71,83,89,92,92,93],
            "wind_speed_10m": [2.4,2.4,2.6,3.2,3.2,3.3,4.0,4.7,4.3,4.5,5.4,5.4,4.7,5.9,6.2,6.5,4.3,5.1,4.7,4.7,4.4,4.5,5.2,5.6,
                               6.2,5.8,5.4,5.1,4.4,4.0,4.1,4.0,4.3,3.6,3.3,3.1,3.8,4.3,4.5,5.1,5.4,4.8,5.6,5.4,4.6,3.9,4.5,3.7],
            "precipitation_probability": [100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,100,95,90,85,63,40,20,13,10,
                                          5,0,3,3,0,0,0,0,0,0,0,0,0,0,0,3,5,20,15,25,23,45,50,53],
        },
        "daily": {
            "time": ["2026-03-26", "2026-03-27", "2026-03-28"],
            "temperature_2m_max": [11.8, 16.5, 17.8],
            "temperature_2m_min": [8.0, 8.4, 8.8],
            "precipitation_probability_max": [100, 53, 63],
            "sunrise": ["2026-03-26T05:37", "2026-03-27T05:35", "2026-03-28T05:34"],
            "sunset": ["2026-03-26T17:57", "2026-03-27T17:58", "2026-03-28T17:59"],
        },
    }

    collector._merge_api_data(
        "https://open-meteo.com/en/docs?latitude=35.68&longitude=139.65",
        real_data,
    )

    # T99: count hours above 10.0°C today
    # Today's temps: [8.4,8.1,8.0,8.6,8.5,8.2,8.5,8.6,8.8,10.1,10.4,10.8,11.7,11.8,11.5,11.2,11.5,11.3,10.8,10.5,10.1,10.0,9.9,9.8]
    # Strictly above 10.0: indices 9-20 minus those <=10.0 → 10.1,10.4,10.8,11.7,11.8,11.5,11.2,11.5,11.3,10.8,10.5,10.1 = 12
    result_t99 = run_async(
        OpenMeteoHourlyThresholdTemplate().get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "metric_field": "temperature_2m", "threshold": 10.0, "is_above": True,
        })
    )
    assert result_t99.success is True
    assert result_t99.value == "12"

    # T100: daylight duration day 0 → sunrise 05:37, sunset 17:57 = 12h 20m
    result_t100 = run_async(
        OpenMeteoSunriseSunsetTemplate().get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "day_idx": 0, "day_label": "today",
        })
    )
    assert result_t100.success is True
    assert result_t100.value == "12h 20m"

    # T101: peak wind speed today
    # Wind: [2.4,2.4,2.6,3.2,3.2,3.3,4.0,4.7,4.3,4.5,5.4,5.4,4.7,5.9,6.2,6.5,4.3,5.1,4.7,4.7,4.4,4.5,5.2,5.6]
    # Max = 6.5 at index 15 → 15:00
    result_t101 = run_async(
        OpenMeteoHourlyTimeOfTemplate().get_ground_truth({
            "city_name": "Tokyo", "coord_key": "35.68,139.65",
            "is_max": True, "metric_field": "wind_speed_10m",
        })
    )
    assert result_t101.success is True
    assert result_t101.value == "15:00"


def test_build_data_html_includes_sunrise_sunset():
    plugin = OpenMeteoPlugin()
    html = plugin._build_data_html({
        "current_weather": {"temperature": 12.5, "windspeed": 5.0, "winddirection": 180},
        "daily": {
            "time": ["2026-03-17"],
            "temperature_2m_max": [16.0],
            "temperature_2m_min": [9.0],
            "precipitation_probability_max": [30],
            "sunrise": ["2026-03-17T06:00"],
            "sunset": ["2026-03-17T18:05"],
        },
        "hourly": {"time": [], "temperature_2m": []},
    })
    assert "Sunrise" in html
    assert "Sunset" in html
    assert "2026-03-17T06:00" in html
    assert "2026-03-17T18:05" in html
