"""Title word count filter template for Hacker News - MEDIUM DIFFICULTY.

Asks how many of the top N stories on HN have titles longer than K words.
Agent starts on /newest, must navigate to the ranked homepage.
Tests text analysis + counting — a capability no existing HN template covers
(existing templates use only score/comments, never title content).

SFT defense:
- Story titles change hourly as the front page rotates.
- Word threshold includes a seed-derived jitter (±1), preventing
  fixed threshold-to-count mappings.
- Title length distributions vary by news cycle and are not stable
  enough for climatological estimation.

Effective variants: 4 N-values × 5 base thresholds × continuous jitter
                    × 3 patterns × hourly data rotation.
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

STORY_COUNTS = [10, 15, 20, 30]
BASE_WORD_THRESHOLDS = [4, 6, 8, 10, 12]

PATTERNS = [
    "Among the top {n} stories on Hacker News, how many have titles with more than {k} words?",
    "On the HN front page, count how many of the top {n} story titles are longer than {k} words.",
    "Look at the top {n} stories on Hacker News. How many titles contain more than {k} words?",
]


@register_template("hackernews_title_word_count")
class HackerNewsTitleWordCountTemplate(QuestionTemplate):
    """
    MEDIUM: Count stories whose title exceeds a jittered word threshold.

    Tests text analysis — must read actual titles and count words.
    Jittered threshold prevents SFT from memorising fixed distributions.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("hackernews_title_word_count")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)
        n = STORY_COUNTS[variant % len(STORY_COUNTS)] if variant is not None else rng.choice(STORY_COUNTS)

        base_k = rng.choice(BASE_WORD_THRESHOLDS)
        jitter = rng.choice([-1, 0, 0, 1])  # slight jitter, biased toward no change
        k = max(2, base_k + jitter)

        pattern = rng.choice(PATTERNS)

        return GeneratedQuestion(
            question_text=pattern.format(n=n, k=k),
            start_url="https://news.ycombinator.com/newest",
            variables={"n": n, "k": k},
            validation_info={"story_count": n, "word_threshold": k},
            template_name=self.name,
            expected_steps=5,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        n = validation_info.get("story_count", 10)
        k = validation_info.get("word_threshold", 8)
        return f"""Task-Specific Rules (HN Title Word Count):
- Among the top {n} stories on the HN front page, count titles with more than {k} words
- A word is any whitespace-separated token in the title
- Answer should be a whole number (0 to {n})
- Score 1.0: Exact count
- Score 0.5: Off by 1
- Score 0.0: Off by more than 1 or no numeric answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        n = validation_info.get("story_count", 10)
        k = validation_info.get("word_threshold", 8)

        stories, failure = collect_homepage_stories(n)
        if failure is not None:
            return failure

        count = sum(1 for s in stories if len(str(s.get("title", "")).split()) > k)
        return GroundTruthResult.ok(str(count))

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
