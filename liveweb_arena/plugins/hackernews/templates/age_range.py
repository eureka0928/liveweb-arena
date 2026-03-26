"""Story age range template for Hacker News - MEDIUM DIFFICULTY.

Asks how many hours apart the newest and oldest stories among the top N
on HN were posted. Agent starts on /newest, must navigate to the ranked
homepage. Fills the TIME-SENSITIVITY gap — no existing template uses
the `time` field.

SFT defense:
- Story turnover varies dramatically: hot-news days have rapid cycling
  (spread ~4-8h), slow days have long spreads (~20-48h).
- SFT has no way to predict current front-page age spread.
- Answer space (~1-48 hours) is continuous, not a small integer set.

Effective variants: 5 story-count values × 3 patterns × hourly data rotation.
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

from .common import collect_homepage_stories

STORY_COUNTS = [5, 10, 15, 20, 30]

PATTERNS = [
    "Among the top {n} stories on Hacker News, how many hours apart were the most recent and oldest stories posted?",
    "On the HN front page, what is the time span in hours between the newest and oldest of the top {n} stories?",
    "Look at the top {n} stories on Hacker News. How many hours separate the newest post from the oldest?",
]


@register_template("hackernews_age_range")
class HackerNewsAgeRangeTemplate(QuestionTemplate):
    """
    MEDIUM: Compute time spread of the top N stories on HN.

    Tests time-based reasoning — a capability gap identified in CLAUDE.md.
    Requires reading posting timestamps and computing the difference.
    Story turnover is unpredictable, making the answer SFT-resistant.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("hackernews_age_range")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)
        n = STORY_COUNTS[variant % len(STORY_COUNTS)] if variant is not None else rng.choice(STORY_COUNTS)
        pattern = rng.choice(PATTERNS)

        return GeneratedQuestion(
            question_text=pattern.format(n=n),
            start_url="https://news.ycombinator.com/newest",
            variables={"n": n},
            validation_info={"story_count": n},
            template_name=self.name,
            expected_steps=5,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        n = validation_info.get("story_count", 10)
        return f"""Task-Specific Rules (HN Age Range):
- Look at the top {n} stories on the HN front page
- Find the posting times of the newest and oldest stories
- Report the difference in hours (round to nearest integer)
- Score 1.0: Within ±1 hour of the correct span
- Score 0.5: Within ±3 hours
- Score 0.0: Off by more than 3 hours or no numeric answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        n = validation_info.get("story_count", 10)
        stories, failure = collect_homepage_stories(n)
        if failure is not None:
            return failure

        times = []
        for s in stories:
            ts = s.get("time")
            if ts is None:
                return GroundTruthResult.fail(
                    f"Story rank {s.get('rank')} missing 'time' field"
                )
            times.append(int(ts))

        newest = max(times)
        oldest = min(times)
        spread_hours = round((newest - oldest) / 3600)

        return GroundTruthResult.ok(f"{spread_hours}")

    async def validate_answer(
        self, answer: str, validation_info: Dict[str, Any]
    ) -> ValidationResult:
        return ValidationResult(
            score=0.0, is_correct=False, expected=None, actual=answer,
            details="Use LLM validation",
        )

    def get_ground_truth_trigger(self, validation_info: dict) -> TriggerConfig:
        return TriggerConfig(trigger=UrlPatternTrigger(domains=["news.ycombinator.com"]))

    @classmethod
    def get_cache_source(cls) -> str:
        return "hackernews"

    def get_gt_source(self) -> GTSourceType:
        return self.GT_SOURCE
