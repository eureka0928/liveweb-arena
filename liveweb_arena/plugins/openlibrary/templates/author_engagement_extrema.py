"""Author engagement extrema template for Open Library - MEDIUM DIFFICULTY.

RL-friendly design:
- Requires searching for an author and scanning multiple results
- Dynamic data: want_to_read counts and ratings change continuously
- Entity pool: 81 authors × (highest-wtr: 7 + highest-rc: 2 + lowest-wtr: 3) = 972 variants
- Computation required: must compare values across N books to find extremum
- Strict sort matching: GT only accepts data from sort=editions pages (no unsorted fallback)
- Missing ratings_count causes GT failure; only want_to_read_count defaults to 0 when absent
- ratings_count variants capped to N∈{3,5} to limit GT-fail from sparse OL data
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


class ExtremaType(Enum):
    """Whether to find the highest or lowest value."""
    HIGHEST = "highest"
    LOWEST = "lowest"


class EngagementMetric(Enum):
    """Reader engagement metrics confirmed visible on search result pages."""
    WANT_TO_READ = ("want_to_read_count", "want-to-read count")
    RATINGS_COUNT = ("ratings_count", "number of ratings")


# ratings_count is excluded from LOWEST extrema because the OL API omits
# the field for unrated works; missing-as-zero would always "win" lowest.
_LOWEST_METRICS = [EngagementMetric.WANT_TO_READ]

RESULT_COUNTS = [3, 5, 7, 10, 15, 20, 25]

# For lowest extrema, cap work_count to avoid missing-as-zero domination.
# At work_count >= 10, many authors have missing want_to_read_count entries
# that coerce to 0, making the GT answer = alphabetically first zero-book.
_LOWEST_RESULT_COUNTS = [3, 5, 7]

# ratings_count is sparse in OL data (20-40% of top-N missing at N≥7).
# Cap to small N where coverage is highest to limit GT-fail exposure.
_RATINGS_RESULT_COUNTS = [3, 5]

PATTERNS = {
    ExtremaType.HIGHEST: [
        (
            'Search Open Library for books by "{author}" sorted by most editions. '
            "Among the first {n} results, which book has the highest {metric_label}? "
            "Answer with the book title only."
        ),
        (
            'On Open Library, look up books by "{author}" (most editions). '
            "Of the top {n} results, which has the most {metric_label}? "
            "Reply with just the title."
        ),
    ],
    ExtremaType.LOWEST: [
        (
            'Search Open Library for books by "{author}" sorted by most editions. '
            "Among the first {n} results, which book has the lowest {metric_label}? "
            "Answer with the book title only."
        ),
        (
            'On Open Library, look up books by "{author}" (most editions). '
            "Of the top {n} results, which has the fewest {metric_label}? "
            "Reply with just the title."
        ),
    ],
}


@register_template("openlibrary_author_engagement_extrema")
class OpenLibraryAuthorEngagementExtremaTemplate(QuestionTemplate):
    """Find the book with the highest/lowest engagement metric among an author's top works.

    MEDIUM difficulty: requires searching for an author, reading engagement
    metrics across multiple results, and identifying the extremum.
    """

    GT_SOURCE = GTSourceType.PAGE_ONLY

    def __init__(self):
        super().__init__("openlibrary_author_engagement_extrema")

    def generate(self, seed: int, variant: Optional[int] = None) -> GeneratedQuestion:
        rng = random.Random(seed)

        author_name, author_query = rng.choice(ENGAGEMENT_AUTHOR_POOL)
        extrema = rng.choice(list(ExtremaType))
        pool = _LOWEST_METRICS if extrema == ExtremaType.LOWEST else list(EngagementMetric)
        metric = rng.choice(pool)

        if extrema == ExtremaType.LOWEST:
            counts = _LOWEST_RESULT_COUNTS
        elif metric == EngagementMetric.RATINGS_COUNT:
            counts = _RATINGS_RESULT_COUNTS
        else:
            counts = RESULT_COUNTS
        count = (
            counts[variant % len(counts)]
            if variant is not None
            else rng.choice(counts)
        )

        search_query = f'author:"{author_query}"'
        pattern = rng.choice(PATTERNS[extrema])
        question_text = pattern.format(
            author=author_name,
            n=count,
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
                "extrema": extrema.value,
                "metric": metric.value[0],
            },
            validation_info={
                "author_name": author_name,
                "author_query": author_query,
                "search_query": search_query,
                "sort": "editions",
                "work_count": count,
                "extrema": extrema.value,
                "metric": metric.value[0],
                "metric_label": metric.value[1],
            },
            template_name=self.name,
            expected_steps=7,
        )

    def get_validation_rules(self, validation_info: Dict[str, Any]) -> str:
        author = validation_info.get("author_name", "")
        count = validation_info.get("work_count", "")
        extrema = validation_info.get("extrema", "")
        metric_label = validation_info.get("metric_label", "")
        return f"""Task-Specific Rules (Open Library Author Engagement Extrema):
- Author: "{author}"
- Find the {extrema} {metric_label} among the first {count} results
- Score 1.0: Correct book title
- Score 0.0: Wrong title or no answer
- Tie rule: alphabetically earlier title wins"""

    async def get_ground_truth(self, validation_info: Dict[str, Any]) -> GroundTruthResult:
        collected = get_collected_data()
        if not collected:
            return GroundTruthResult.fail("No Open Library data collected")

        author_name = validation_info.get("author_name")
        search_query = validation_info.get("search_query")
        sort = validation_info.get("sort")
        work_count = validation_info.get("work_count")
        extrema = validation_info.get("extrema")
        metric = validation_info.get("metric")

        if (
            not isinstance(author_name, str)
            or not isinstance(search_query, str)
            or not isinstance(sort, str)
            or not isinstance(work_count, int)
            or not isinstance(extrema, str)
            or not isinstance(metric, str)
        ):
            return GroundTruthResult.fail("Missing or invalid extrema inputs")
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
                f"Only {len(works_dict)} works collected, need {work_count}"
            )

        ranked = sorted(works_dict.values(), key=lambda w: w.get("rank", 999))
        top_n = ranked[:work_count]

        best_title: Optional[str] = None
        best_value: Optional[float] = None
        for work in top_n:
            title = work.get("title")
            if not isinstance(title, str):
                return GroundTruthResult.fail("Work missing title field")
            try:
                value = safe_metric_value(work, metric)
            except ValueError as exc:
                return GroundTruthResult.fail(str(exc))
            is_better = (
                best_value is None
                or (extrema == "highest" and value > best_value)
                or (extrema == "lowest" and value < best_value)
                or (value == best_value and title.casefold() < best_title.casefold())
            )
            if is_better:
                best_title = title
                best_value = value

        if best_title is None:
            return GroundTruthResult.fail("No works with valid metric values found")

        return GroundTruthResult.ok(best_title)

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
