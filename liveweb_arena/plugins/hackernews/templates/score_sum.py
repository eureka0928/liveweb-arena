"""Score sum template for Hacker News - MEDIUM DIFFICULTY.

Asks for the total combined score (points) of the top N stories on HN.

Agent starts on /newest (time-sorted submissions), must navigate to the
ranked homepage to find "top stories", read N scores, and sum them.
Tests aggregation — a capability no existing HN template covers.

SFT defense:
- Scores change hourly; total sum is highly volatile (~500-15000 range).
- ±10% tolerance for 1.0 is tight on a wide, shifting range.
- SFT cannot estimate the sum without reading current scores.

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
    "What is the total combined score (points) of the top {n} stories currently on Hacker News?",
    "On the Hacker News front page, sum up the scores of the top {n} stories. What is the total?",
    "Add together the point counts of the first {n} stories on HN right now. What do you get?",
]


@register_template("hackernews_score_sum")
class HackerNewsScoreSumTemplate(QuestionTemplate):
    """
    MEDIUM: Sum scores of the top N stories on HN.

    Tests aggregation — must visit homepage, read all N scores, and sum.
    Scores change hourly, making the total highly volatile and SFT-resistant.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("hackernews_score_sum")

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
        return f"""Task-Specific Rules (HN Score Sum):
- Sum the scores (points) of the top {n} stories on the HN front page
- Answer should be a single integer
- Score 1.0: Within ±10% of the correct total
- Score 0.5: Within ±25%
- Score 0.0: Outside ±25% or no numeric answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        n = validation_info.get("story_count", 10)
        stories, failure = collect_homepage_stories(n)
        if failure is not None:
            return failure

        total = sum(int(s.get("score", 0)) for s in stories)
        return GroundTruthResult.ok(str(total))

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
