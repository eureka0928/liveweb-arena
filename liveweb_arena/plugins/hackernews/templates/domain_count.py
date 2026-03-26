"""Domain diversity template for Hacker News - MEDIUM DIFFICULTY.

Asks how many distinct website domains are linked from the top N stories.
Agent starts on /newest, must navigate to the ranked homepage.
Tests URL parsing + deduplication — uses the `url` field which no existing
HN template touches.

SFT defense:
- Which domains appear on HN changes daily with the news cycle.
- During a big event (e.g., Apple keynote), many stories link to the
  same domain, reducing diversity. On normal days, diversity is higher.
- SFT cannot predict the current domain distribution.

Effective variants: 5 N-values × 3 patterns × hourly data rotation.
"""

import random
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from liveweb_arena.core.validators.base import (
    QuestionTemplate, GeneratedQuestion, ValidationResult, register_template,
)
from liveweb_arena.core.ground_truth_trigger import (
    UrlPatternTrigger, TriggerConfig, GroundTruthResult,
)
from liveweb_arena.core.gt_collector import GTSourceType

from .common import collect_homepage_stories

STORY_COUNTS = [10, 15, 20, 25, 30]

PATTERNS = [
    "Among the top {n} stories on Hacker News, how many link to distinct website domains?",
    "On the HN front page, count the number of unique domains linked by the top {n} stories.",
    "Look at the top {n} stories on Hacker News. How many different website domains do they link to?",
]


def _extract_domain(url: str) -> Optional[str]:
    """Extract the registrable domain from a URL, stripping www prefix."""
    try:
        host = urlparse(url).hostname
        if not host:
            return None
        host = host.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return None


@register_template("hackernews_domain_count")
class HackerNewsDomainCountTemplate(QuestionTemplate):
    """
    MEDIUM: Count distinct link domains among top N stories.

    Tests URL parsing and deduplication. The `url` field is unused by all
    existing HN templates. Domain diversity fluctuates with the news cycle.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("hackernews_domain_count")

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
        return f"""Task-Specific Rules (HN Domain Count):
- Count the number of distinct website domains linked from the top {n} HN stories
- Stories without external links (e.g. Ask HN) do not contribute a domain
- Ignore www. prefix when comparing domains (www.example.com = example.com)
- Answer should be a whole number
- Score 1.0: Exact count
- Score 0.5: Off by 1-2
- Score 0.0: Off by more than 2 or no numeric answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        n = validation_info.get("story_count", 10)
        stories, failure = collect_homepage_stories(n)
        if failure is not None:
            return failure

        domains = set()
        for s in stories:
            url = s.get("url")
            if not url:
                continue
            domain = _extract_domain(url)
            if domain:
                domains.add(domain)

        return GroundTruthResult.ok(str(len(domains)))

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
