"""Reading stats filter template for Open Library - HARD DIFFICULTY.

RL-friendly design:
- Requires searching for an author and scanning engagement metrics per book
- Dynamic data: want_to_read counts and ratings change continuously
- Entity pool: 81 authors × (wtr: 4 thresholds × 3 counts + rc: 4 thresholds × 1 count) = 1,296 variants
- Counting task: agent must check each book against a threshold (no single-sort shortcut)
- ratings_count variants capped to N=5 to limit GT-fail from sparse OL data
"""

import random
from enum import Enum
from typing import Any, Dict, List, Optional
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


class ReaderMetric(Enum):
    """Reader engagement metrics with per-metric thresholds."""
    WANT_TO_READ = ("want_to_read_count", "people who want to read them")
    RATINGS_COUNT = ("ratings_count", "ratings")


THRESHOLDS: Dict[ReaderMetric, List[int]] = {
    ReaderMetric.WANT_TO_READ: [100, 200, 500, 1000],
    ReaderMetric.RATINGS_COUNT: [30, 50, 100, 200],
}

RESULT_COUNTS = [5, 10, 15]

# ratings_count is sparse in OL data (22% of authors missing at N=5, 57% at N=10).
# Cap to N=5 for ratings_count to keep GT-fail exposure under ~11%.
_RATINGS_RESULT_COUNTS = [5]

PATTERNS = [
    (
        'Search Open Library for books by "{author}" sorted by most editions. '
        "Among the first {n} results, how many have more than {threshold} "
        "{metric_label}?"
    ),
    (
        'On Open Library, look up books by "{author}" (most editions). '
        "Of the top {n} results, count how many have over {threshold} "
        "{metric_label}."
    ),
    (
        'Find books by "{author}" on Open Library (most editions). '
        "How many of the first {n} results have more than {threshold} "
        "{metric_label}?"
    ),
]


@register_template("openlibrary_reading_stats_filter")
class OpenLibraryReadingStatsFilterTemplate(QuestionTemplate):
    """Count books in an author's catalog meeting an engagement threshold.

    HARD difficulty: requires scanning each book's engagement metric and
    counting those above a threshold. Cannot be solved by sorting a single
    column — the threshold is on a different metric than the sort order.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openlibrary_reading_stats_filter")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        metrics = list(ReaderMetric)
        metric = (
            metrics[variant % len(metrics)]
            if variant is not None
            else rng.choice(metrics)
        )

        author_name, author_query = rng.choice(ENGAGEMENT_AUTHOR_POOL)
        counts = _RATINGS_RESULT_COUNTS if metric == ReaderMetric.RATINGS_COUNT else RESULT_COUNTS
        count = rng.choice(counts)
        threshold = rng.choice(THRESHOLDS[metric])

        search_query = f'author:"{author_query}"'
        pattern = rng.choice(PATTERNS)
        question_text = pattern.format(
            author=author_name,
            n=count,
            threshold=threshold,
            metric_label=metric.value[1],
        )
        query_encoded = quote_plus(search_query)
        start_url = f"https://openlibrary.org/search?q={query_encoded}&sort=editions"

        return GeneratedQuestion(
            question_text=question_text,
            start_url=start_url,
            variables={
                "author": author_name,
                "work_count": count,
                "metric": metric.value[0],
                "threshold": threshold,
            },
            validation_info={
                "author_name": author_name,
                "author_query": author_query,
                "search_query": search_query,
                "sort": "editions",
                "work_count": count,
                "metric": metric.value[0],
                "metric_label": metric.value[1],
                "threshold": threshold,
            },
            template_name=self.name,
            expected_steps=8,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        author = validation_info.get("author_name", "")
        count = validation_info.get("work_count", "")
        metric_label = validation_info.get("metric_label", "")
        threshold = validation_info.get("threshold", "")
        return f"""Task-Specific Rules (Open Library Reading Stats Filter):
- Author: "{author}"
- Count books among top {count} with > {threshold} {metric_label}
- Score 1.0: Exact count match
- Score 0.5: Count within ±1 of correct answer
- Score 0.0: Wrong count or no answer"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        collected = get_collected_data()
        if not collected:
            return GroundTruthResult.fail("No Open Library data collected")

        author_name = validation_info.get("author_name")
        search_query = validation_info.get("search_query")
        sort = validation_info.get("sort")
        work_count = validation_info.get("work_count")
        metric = validation_info.get("metric")
        threshold = validation_info.get("threshold")

        if (
            not isinstance(author_name, str)
            or not isinstance(search_query, str)
            or not isinstance(sort, str)
            or not isinstance(work_count, int)
            or not isinstance(metric, str)
            or not isinstance(threshold, int)
        ):
            return GroundTruthResult.fail("Missing or invalid filter inputs")
        if work_count <= 0:
            return GroundTruthResult.fail(f"Invalid work_count: {work_count}")

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
            return GroundTruthResult.fail("Collected search data missing works dictionary")
        if len(works_dict) < work_count:
            return GroundTruthResult.fail(
                f"Only {len(works_dict)} works collected for '{author_name}', "
                f"need {work_count}"
            )

        ranked = sorted(works_dict.values(), key=lambda w: w.get("rank", 999))
        top_n = ranked[:work_count]

        match_count = 0
        for work in top_n:
            try:
                value = safe_metric_value(work, metric)
            except ValueError as exc:
                return GroundTruthResult.fail(str(exc))
            if int(value) > threshold:
                match_count += 1

        return GroundTruthResult.ok(str(match_count))

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
