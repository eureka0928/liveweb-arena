"""Author comparison template for Open Library - MEDIUM/HARD DIFFICULTY.

RL-friendly design:
- Requires TWO separate author searches and cross-page comparison
- Dynamic data: engagement metrics change continuously as users interact
- Large entity pool: C(81,2)×2 metrics×2 result counts = 12,960 variants
- Computation required: sum metric across N books for each author, compute difference
- Numeric answer (absolute difference) avoids 50% random baseline of binary choice
"""

import random
from enum import Enum
from typing import Any, Dict, Optional
from urllib.parse import quote_plus

from liveweb_arena.core.ground_truth_trigger import (
    GroundTruthResult,
    TriggerConfig,
    UrlPatternTrigger,
)
from liveweb_arena.core.gt_collector import GTSourceType
from liveweb_arena.core.validators.base import (
    GeneratedQuestion,
    QuestionTemplate,
    ValidationResult,
    register_template,
)
from .author_editions import ENGAGEMENT_AUTHOR_POOL
from .common import find_author_search_entry, get_collected_data, safe_metric_value


class AuthorMetric(Enum):
    """Engagement metrics for cross-author comparison."""
    WANT_TO_READ = ("want_to_read_count", "total want-to-read count")
    RATINGS_COUNT = ("ratings_count", "total number of ratings")


RESULT_COUNTS = [3, 5]

PATTERNS = [
    (
        'On Open Library, search for books by "{author_a}" and "{author_b}", '
        "both sorted by most editions. What is the absolute difference in "
        "{metric_label} between the first {n} results for each author? "
        "Answer with just the number."
    ),
    (
        'Compare "{author_a}" and "{author_b}" on Open Library. For each author, '
        "look at the top {n} books (sorted by most editions) and sum their "
        "{metric_label}. What is the absolute difference between the two totals? "
        "Reply with just a number."
    ),
    (
        'Search Open Library for books by "{author_a}" and by "{author_b}" '
        "(most editions). Sum the {metric_label} across each author's top {n} "
        "results. What is the absolute difference? Answer with the number only."
    ),
]


@register_template("openlibrary_author_comparison")
class OpenLibraryAuthorComparisonTemplate(QuestionTemplate):
    """Compare aggregate engagement metrics between two authors' top works.

    MEDIUM/HARD difficulty: requires two separate author searches, summing
    a metric across top N results for each, then comparing the totals.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openlibrary_author_comparison")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        metrics = list(AuthorMetric)
        metric = (
            metrics[variant % len(metrics)]
            if variant is not None
            else rng.choice(metrics)
        )

        (name_a, query_a), (name_b, query_b) = rng.sample(ENGAGEMENT_AUTHOR_POOL, 2)

        # Randomly swap order to prevent position bias
        if rng.random() > 0.5:
            name_a, query_a, name_b, query_b = name_b, query_b, name_a, query_a

        count = rng.choice(RESULT_COUNTS)
        search_query_a = f'author:"{query_a}"'
        search_query_b = f'author:"{query_b}"'

        pattern = rng.choice(PATTERNS)
        question_text = pattern.format(
            author_a=name_a,
            author_b=name_b,
            n=count,
            metric_label=metric.value[1],
        )

        query_encoded_a = quote_plus(search_query_a)
        start_url = (
            f"https://openlibrary.org/search?q={query_encoded_a}&sort=editions"
        )

        return GeneratedQuestion(
            question_text=question_text,
            start_url=start_url,
            variables={
                "author_a": name_a,
                "author_b": name_b,
                "metric": metric.value[0],
                "work_count": count,
            },
            validation_info={
                "author_a_name": name_a,
                "author_a_query": query_a,
                "search_query_a": search_query_a,
                "author_b_name": name_b,
                "author_b_query": query_b,
                "search_query_b": search_query_b,
                "sort": "editions",
                "work_count": count,
                "metric": metric.value[0],
                "metric_label": metric.value[1],
            },
            template_name=self.name,
            expected_steps=12,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        author_a = validation_info.get("author_a_name", "")
        author_b = validation_info.get("author_b_name", "")
        count = validation_info.get("work_count", "")
        metric_label = validation_info.get("metric_label", "")
        return f"""Task-Specific Rules (Open Library Author Comparison):
- Compare: "{author_a}" vs "{author_b}"
- Metric: {metric_label} summed across top {count} results
- Answer: absolute difference between the two totals (a single number)
- Score 1.0: Exact difference
- Score 0.5: Within ±10% of correct difference
- Score 0.0: Wrong value or no answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        collected = get_collected_data()
        if not collected:
            return GroundTruthResult.fail("No Open Library data collected")

        author_a_name = validation_info.get("author_a_name")
        author_b_name = validation_info.get("author_b_name")
        search_query_a = validation_info.get("search_query_a")
        search_query_b = validation_info.get("search_query_b")
        sort = validation_info.get("sort")
        work_count = validation_info.get("work_count")
        metric = validation_info.get("metric")

        if (
            not isinstance(author_a_name, str)
            or not isinstance(author_b_name, str)
            or not isinstance(search_query_a, str)
            or not isinstance(search_query_b, str)
            or not isinstance(sort, str)
            or not isinstance(work_count, int)
            or not isinstance(metric, str)
        ):
            return GroundTruthResult.fail("Missing or invalid comparison inputs")
        if work_count <= 0:
            return GroundTruthResult.fail(f"Invalid work_count: {work_count}")

        sum_a = self._sum_metric(
            collected, author_a_name, search_query_a, sort, work_count, metric,
        )
        if isinstance(sum_a, GroundTruthResult):
            return sum_a

        sum_b = self._sum_metric(
            collected, author_b_name, search_query_b, sort, work_count, metric,
        )
        if isinstance(sum_b, GroundTruthResult):
            return sum_b

        return GroundTruthResult.ok(str(abs(sum_a - sum_b)))

    @staticmethod
    def _sum_metric(
        collected: Dict[str, Dict[str, Any]],
        author_name: str,
        search_query: str,
        sort: str,
        work_count: int,
        metric: str,
    ) -> "int | GroundTruthResult":
        """Sum a metric across an author's top N search results.

        Returns the integer sum on success, or a GroundTruthResult on failure.
        """
        data = find_author_search_entry(
            collected,
            search_query=search_query,
            sort=sort,
        )
        if data is None:
            ol_keys = [k for k in collected if k.startswith("ol:")][:5]
            return GroundTruthResult.not_collected(
                f"Did not collect search data for author '{author_name}' "
                f"sorted by '{sort}'. Collected OL keys: {ol_keys}"
            )

        works_dict = data.get("works")
        if not isinstance(works_dict, dict):
            return GroundTruthResult.fail(
                f"Collected data for '{author_name}' missing works dictionary"
            )
        if len(works_dict) < work_count:
            return GroundTruthResult.fail(
                f"Only {len(works_dict)} works collected for '{author_name}', "
                f"need {work_count}"
            )

        ranked = sorted(works_dict.values(), key=lambda w: w.get("rank", 999))
        top_n = ranked[:work_count]

        total = 0
        for work in top_n:
            try:
                value = safe_metric_value(work, metric)
            except ValueError as exc:
                return GroundTruthResult.fail(str(exc))
            total += int(value)

        return total

    async def validate_answer(
        self,
        answer: str,
        validation_info: Dict[str, Any],
    ) -> ValidationResult:
        return ValidationResult(
            score=0.0,
            is_correct=False,
            expected=None,
            actual=answer,
            details="Use LLM validation",
        )

    def get_ground_truth_trigger(self, validation_info: dict) -> TriggerConfig:
        trigger = UrlPatternTrigger(domains=["openlibrary.org"])
        return TriggerConfig(trigger=trigger)

    @classmethod
    def get_cache_source(cls) -> str:
        return "openlibrary"

    def get_gt_source(self) -> GTSourceType:
        return self.GT_SOURCE
