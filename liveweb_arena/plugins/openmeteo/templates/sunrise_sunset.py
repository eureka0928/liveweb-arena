"""Sunrise/sunset time template for Open Meteo - MEDIUM DIFFICULTY.

Asks for the exact sunrise or sunset time in a city on a given day.
The agent starts on the generic docs page, finds the city, then reads
the sunrise or sunset time from the daily forecast table.

Dynamic data: sunrise/sunset times shift by ~1-4 minutes daily.
Computation required: agent must locate and read the specific time.

SFT defense:
- Answer is an exact HH:MM value (~1440 possible values, random baseline ~0%).
- An LLM can estimate sunrise/sunset from latitude + date to ±15-30 min,
  but rarely within the ±2 min required for full score.
- The 0.5 tier (±10 min) is tight enough that climatological estimates
  fail for most of the 170-city pool (especially non-capital, high-latitude,
  and Southern-Hemisphere cities where LLM training data is sparse).

Effective variants: 170 cities x 2 (sunrise/sunset) x 3 days = 1,020 (>500).
"""

import random
from typing import Any, Dict, Optional

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType

from .common import DOCS_HOME_URL, get_collected_location_data
from .variables import CITIES


DAY_OPTIONS = [
    (0, "today"),
    (1, "tomorrow"),
    (2, "the day after tomorrow"),
]

PATTERNS_SUNRISE = [
    "According to Open-Meteo, at what time is sunrise in {city} {day_label}?",
    "Using Open-Meteo, find the exact sunrise time for {city} {day_label}.",
    "On Open-Meteo, what time does the sun rise in {city} {day_label}?",
]

PATTERNS_SUNSET = [
    "According to Open-Meteo, at what time is sunset in {city} {day_label}?",
    "Using Open-Meteo, find the exact sunset time for {city} {day_label}.",
    "On Open-Meteo, what time does the sun set in {city} {day_label}?",
]


@register_template("openmeteo_sunrise_sunset")
class OpenMeteoSunriseSunsetTemplate(QuestionTemplate):
    """
    MEDIUM: Read the exact sunrise or sunset time from the daily forecast.

    Requires navigating to the city page and reading a specific time value.
    Large answer space (HH:MM) prevents SFT from achieving high scores via
    world-knowledge estimation.
    170 cities x 2 (sunrise/sunset) x 3 days = 1,020 effective variants.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openmeteo_sunrise_sunset")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        city = rng.choice(CITIES)
        day_idx, day_label = rng.choice(DAY_OPTIONS)
        is_sunrise = rng.choice([True, False])

        patterns = PATTERNS_SUNRISE if is_sunrise else PATTERNS_SUNSET
        question_text = rng.choice(patterns).format(
            city=city.display_name,
            day_label=day_label,
        )

        return GeneratedQuestion(
            question_text=question_text,
            start_url=DOCS_HOME_URL,
            variables={"city": city.name, "day_idx": day_idx, "is_sunrise": is_sunrise},
            validation_info={
                "city_name": city.name,
                "coord_key": city.coord_key,
                "day_idx": day_idx,
                "day_label": day_label,
                "is_sunrise": is_sunrise,
            },
            template_name=self.name,
            expected_steps=7,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        city = validation_info.get("city_name", "")
        day_label = validation_info.get("day_label", "today")
        is_sunrise = validation_info.get("is_sunrise", True)
        event = "sunrise" if is_sunrise else "sunset"
        return f"""Task-Specific Rules (Open Meteo Sunrise/Sunset Time):
- City: {city}
- Looking for: exact {event} time {day_label}
- Answer should be a time in HH:MM format (e.g. "06:23", "18:45")
- Score 1.0: Within ±2 minutes of the correct time
- Score 0.5: Within ±10 minutes
- Score 0.0: Off by more than 10 minutes or no time given
- Use the daily forecast table on Open-Meteo (not a general estimate)"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        coord_key = validation_info.get("coord_key", "")
        city_name = validation_info.get("city_name", "")
        day_idx = validation_info.get("day_idx", 0)
        is_sunrise = validation_info.get("is_sunrise", True)

        data, failure = get_collected_location_data(coord_key, city_name)
        if failure is not None:
            return failure

        daily = data.get("daily")
        if not daily:
            return GroundTruthResult.fail("No daily data in API response")

        field = "sunrise" if is_sunrise else "sunset"
        values = daily.get(field)
        if not values:
            return GroundTruthResult.fail(f"No {field} data in daily forecast")

        if len(values) <= day_idx:
            return GroundTruthResult.fail(
                f"Need at least {day_idx + 1} days of {field} data"
            )

        raw = values[day_idx]

        # Polar regions may have null sunrise/sunset
        if not raw:
            return GroundTruthResult.fail(
                f"{field.title()} is null for {city_name} on day {day_idx} "
                "(possible polar day/night)"
            )

        # Parse ISO timestamp: "2026-03-20T06:23" → "06:23"
        raw_str = str(raw)
        if "T" in raw_str:
            time_part = raw_str.split("T", 1)[1]
        else:
            time_part = raw_str

        # Validate it looks like a time and truncate to HH:MM
        parts = time_part.split(":")
        if len(parts) < 2:
            return GroundTruthResult.fail(
                f"Cannot parse time from {field} value: {raw!r}"
            )
        time_hhmm = f"{parts[0]}:{parts[1]}"

        return GroundTruthResult.ok(time_hhmm)

    async def validate_answer(
        self, answer: str, validation_info: Dict[str, Any]
    ) -> ValidationResult:
        """Not used — the pipeline uses LLM-based validation via get_validation_rules()."""
        return ValidationResult(
            score=0.0, is_correct=False, expected=None, actual=answer,
            details="Use LLM validation",
        )

    def get_ground_truth_trigger(self, validation_info: dict) -> TriggerConfig:
        trigger = UrlPatternTrigger(domains=["open-meteo.com"])
        return TriggerConfig(trigger=trigger)

    @classmethod
    def get_cache_source(cls) -> str:
        return "openmeteo"

    def get_gt_source(self) -> GTSourceType:
        return self.GT_SOURCE
