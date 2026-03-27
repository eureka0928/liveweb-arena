"""Tests: reading_stats_filter GT, registry, helpers, consistency, pool invariants."""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from liveweb_arena.core.gt_collector import GTSourceType, set_current_gt_collector
from liveweb_arena.core.task_registry import TaskRegistry
from liveweb_arena.plugins.openlibrary.templates.author_comparison import (
    AuthorMetric,
    OpenLibraryAuthorComparisonTemplate,
)
from liveweb_arena.plugins.openlibrary.templates.author_engagement_extrema import (
    EngagementMetric,
    OpenLibraryAuthorEngagementExtremaTemplate,
)
from liveweb_arena.plugins.openlibrary.templates.author_editions import ENGAGEMENT_AUTHOR_POOL
from liveweb_arena.plugins.openlibrary.templates.common import (
    extract_author_filter,
    find_author_search_entry,
    normalize_author_fragment,
)
from liveweb_arena.plugins.openlibrary.templates.reading_stats_filter import (
    OpenLibraryReadingStatsFilterTemplate,
    ReaderMetric,
)


class _DummyCollector:
    def __init__(self, data: Dict[str, Dict[str, Any]]):
        self._data = data

    def get_collected_api_data(self) -> Dict[str, Dict[str, Any]]:
        return self._data


def _run_gt(data: Dict[str, Dict[str, Any]], coro):
    set_current_gt_collector(_DummyCollector(data))
    try:
        return asyncio.run(coro)
    finally:
        set_current_gt_collector(None)


def _make_search_entry(
    query: str, sort: Optional[str], works: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "query": query,
        "sort": sort,
        "works": {work["key"]: work for work in works},
    }


# ── 5. reading_stats_filter GT behavior ───────────────────────────────


def test_filter_counts_above_threshold():
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 10000},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 2000},
            {"key": "/works/OL3W", "rank": 3, "title": "Misery", "want_to_read_count": 2500},
            {"key": "/works/OL4W", "rank": 4, "title": "The Shining", "want_to_read_count": 150},
            {"key": "/works/OL5W", "rank": 5, "title": "Salem's Lot", "want_to_read_count": 50},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 5, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 200,
    }))
    assert result.success is True
    assert result.value == "3"  # It(10000), Carrie(2000), Misery(2500) > 200


def test_filter_returns_zero_when_none_match():
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "The Raven", "want_to_read_count": 10},
            {"key": "/works/OL2W", "rank": 2, "title": "Annabel Lee", "want_to_read_count": 5},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Edgar Allan Poe", "author_query": "edgar allan poe",
        "search_query": 'author:"edgar allan poe"', "sort": "editions",
        "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 500,
    }))
    assert result.success is True
    assert result.value == "0"


def test_filter_exact_threshold_not_counted():
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "The Raven", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "Annabel Lee", "want_to_read_count": 101},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Edgar Allan Poe", "author_query": "edgar allan poe",
        "search_query": 'author:"edgar allan poe"', "sort": "editions",
        "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 100,
    }))
    assert result.success is True
    assert result.value == "1"  # only 101 > 100, not 100 > 100


def test_filter_rejects_unsorted_data():
    """GT must require sort=editions; unsorted data should produce not_collected."""
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:king": _make_search_entry("stephen king", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 10000},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 2000},
            {"key": "/works/OL3W", "rank": 3, "title": "Misery", "want_to_read_count": 2500},
            {"key": "/works/OL4W", "rank": 4, "title": "The Shining", "want_to_read_count": 150},
            {"key": "/works/OL5W", "rank": 5, "title": "Salem's Lot", "want_to_read_count": 50},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 5, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 200,
    }))
    assert result.success is False
    assert result.is_data_not_collected()


def test_filter_not_collected_wrong_author():
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "X", "want_to_read_count": 100},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Mark Twain", "author_query": "mark twain",
        "search_query": 'author:"mark twain"', "sort": "editions",
        "work_count": 5, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 100,
    }))
    assert result.success is False
    assert result.is_data_not_collected()


def test_filter_missing_wtr_treated_as_zero():
    """OL API omits want_to_read_count when the value is zero; GT treats absent as 0."""
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "The Raven", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "Annabel Lee"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Edgar Allan Poe", "author_query": "edgar allan poe",
        "search_query": 'author:"edgar allan poe"', "sort": "editions",
        "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 50,
    }))
    assert result.success is True
    assert result.value == "1"  # only The Raven (100) > 50; Annabel Lee (0) is not


def test_filter_missing_ratings_count_fails_gt():
    """Missing ratings_count should cause GT failure (not default to 0)."""
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "The Raven", "ratings_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "Annabel Lee"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Edgar Allan Poe", "author_query": "edgar allan poe",
        "search_query": 'author:"edgar allan poe"', "sort": "editions",
        "work_count": 2, "metric": "ratings_count",
        "metric_label": "ratings", "threshold": 50,
    }))
    assert result.success is False


def test_filter_non_numeric_metric_causes_gt_failure():
    """Non-null non-numeric metric values should cause a GT fail via safe_metric_value."""
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:poe": _make_search_entry('author:"edgar allan poe"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "The Raven", "want_to_read_count": "N/A"},
            {"key": "/works/OL2W", "rank": 2, "title": "Annabel Lee", "want_to_read_count": 100},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Edgar Allan Poe", "author_query": "edgar allan poe",
        "search_query": 'author:"edgar allan poe"', "sort": "editions",
        "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 50,
    }))
    assert result.success is False


def test_filter_no_collected_data():
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    result = _run_gt({}, tmpl.get_ground_truth({
        "author_name": "X", "author_query": "x",
        "search_query": 'author:"x"', "sort": "editions",
        "work_count": 5, "metric": "want_to_read_count",
        "metric_label": "people who want to read them", "threshold": 100,
    }))
    assert result.success is False


def test_filter_ratings_count_gt():
    """Verify GT works correctly with ratings_count metric (not just want_to_read)."""
    tmpl = OpenLibraryReadingStatsFilterTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "ratings_count": 500},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "ratings_count": 80},
            {"key": "/works/OL3W", "rank": 3, "title": "Misery", "ratings_count": 20},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 3, "metric": "ratings_count",
        "metric_label": "ratings", "threshold": 50,
    }))
    assert result.success is True
    assert result.value == "2"  # It(500) and Carrie(80) > 50; Misery(20) is not


# ── 6. Task registry ──────────────────────────────────────────────────


def test_task_registry_new_template_ids():
    assert TaskRegistry.TEMPLATES[96] == (
        "openlibrary", "openlibrary_author_engagement_extrema",
    )
    assert TaskRegistry.TEMPLATES[97] == (
        "openlibrary", "openlibrary_author_comparison",
    )
    assert TaskRegistry.TEMPLATES[98] == (
        "openlibrary", "openlibrary_reading_stats_filter",
    )


def test_task_registry_version_7_entry():
    found = any(sorted(v) == [96, 97, 98] for v in TaskRegistry.TEMPLATE_VERSIONS)
    assert found, "No TEMPLATE_VERSIONS entry for [96, 97, 98]"


# ── 7. Shared helper refactoring ──────────────────────────────────────


def test_normalize_author_fragment():
    assert normalize_author_fragment("Mark Twain") == "mark twain"
    assert normalize_author_fragment("H.G. Wells") == "h g wells"
    assert normalize_author_fragment("J.K. Rowling") == "j k rowling"
    assert normalize_author_fragment("") == ""


def test_extract_author_filter_standard():
    assert extract_author_filter('author:"mark twain"') == "mark twain"
    assert extract_author_filter("AUTHOR: \"Mark Twain\"") == "mark twain"
    assert extract_author_filter("author:'h.g. wells'") == "h g wells"


def test_extract_author_filter_rejects_plain_text():
    assert extract_author_filter("mark twain") is None
    assert extract_author_filter("") is None


def test_find_author_search_entry_matches():
    collected = {
        "ol:search:twain": _make_search_entry('author:"mark twain"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "X"},
        ]),
    }
    result = find_author_search_entry(
        collected, search_query='author:"mark twain"', sort="editions",
    )
    assert result is not None
    assert result["query"] == 'author:"mark twain"'


def test_find_author_search_entry_rejects_wrong_sort():
    collected = {
        "ol:search:twain": _make_search_entry('author:"mark twain"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "X"},
        ]),
    }
    result = find_author_search_entry(
        collected, search_query='author:"mark twain"', sort="new",
    )
    assert result is None


def test_find_author_search_entry_unsorted_fallback_disabled_by_default():
    collected = {
        "ol:search:christie": _make_search_entry("agatha christie", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "Styles"},
        ]),
    }
    result = find_author_search_entry(
        collected, search_query='author:"agatha christie"', sort="editions",
    )
    assert result is None


def test_find_author_search_entry_matches_unsorted_when_fallback_enabled():
    collected = {
        "ol:search:christie": _make_search_entry("agatha christie", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "Styles"},
        ]),
    }
    result = find_author_search_entry(
        collected,
        search_query='author:"agatha christie"',
        sort="editions",
        allow_unsorted_fallback=True,
    )
    assert result is not None
    assert result["query"] == "agatha christie"


def test_find_author_search_entry_prefers_exact_sort_over_unsorted_fallback():
    collected = {
        "ol:search:unsorted": _make_search_entry("agatha christie", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "Unsorted"},
        ]),
        "ol:search:sorted": _make_search_entry("agatha christie", "editions", [
            {"key": "/works/OL2W", "rank": 1, "title": "Sorted"},
        ]),
    }
    result = find_author_search_entry(
        collected,
        search_query='author:"agatha christie"',
        sort="editions",
        allow_unsorted_fallback=True,
    )
    assert result is not None
    assert result["sort"] == "editions"
    assert result["query"] == "agatha christie"


def test_find_author_search_entry_matches_plain_text_query():
    """Agent typed 'agatha christie' instead of 'author:\"agatha christie\"'."""
    collected = {
        "ol:search:christie": _make_search_entry("agatha christie", "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Styles"},
        ]),
    }
    result = find_author_search_entry(
        collected, search_query='author:"agatha christie"', sort="editions",
    )
    assert result is not None
    assert result["query"] == "agatha christie"


def test_find_author_search_entry_plain_text_wrong_author_no_match():
    """Plain-text fallback must still reject a different author."""
    collected = {
        "ol:search:king": _make_search_entry("stephen king", "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It"},
        ]),
    }
    result = find_author_search_entry(
        collected, search_query='author:"agatha christie"', sort="editions",
    )
    assert result is None


def test_comparison_matches_when_second_author_uses_plain_text():
    """Regression: author_comparison must not return not_collected when the
    agent searches for the second author using plain text."""
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 500},
        ]),
        "ol:search:christie": _make_search_entry("agatha christie", "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles", "want_to_read_count": 100},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_a_name": "Stephen King",
        "author_a_query": "stephen king",
        "search_query_a": 'author:"stephen king"',
        "author_b_name": "Agatha Christie",
        "author_b_query": "agatha christie",
        "search_query_b": 'author:"agatha christie"',
        "sort": "editions", "work_count": 1, "metric": "want_to_read_count",
        "metric_label": "total want-to-read count",
    }))
    assert result.success is True
    assert result.value == "400"  # abs(500 - 100)


# ── 8. Cross-template consistency ─────────────────────────────────────


@pytest.mark.parametrize("cls", [
    OpenLibraryAuthorEngagementExtremaTemplate,
    OpenLibraryAuthorComparisonTemplate,
    OpenLibraryReadingStatsFilterTemplate,
])
def test_gt_source_is_page_only(cls):
    assert cls().get_gt_source() == GTSourceType.PAGE_ONLY


@pytest.mark.parametrize("cls", [
    OpenLibraryAuthorEngagementExtremaTemplate,
    OpenLibraryAuthorComparisonTemplate,
    OpenLibraryReadingStatsFilterTemplate,
])
def test_cache_source_is_openlibrary(cls):
    assert cls.get_cache_source() == "openlibrary"


def test_engagement_extrema_metrics_use_confirmed_visible_fields():
    metric_names = {m.value[0] for m in EngagementMetric}
    assert metric_names == {"want_to_read_count", "ratings_count"}


def test_author_comparison_metrics_use_confirmed_visible_fields():
    metric_names = {m.value[0] for m in AuthorMetric}
    assert metric_names == {"want_to_read_count", "ratings_count"}


def test_reading_filter_metrics_use_confirmed_visible_fields():
    metric_names = {m.value[0] for m in ReaderMetric}
    assert metric_names == {"want_to_read_count", "ratings_count"}


def test_all_new_templates_reuse_engagement_pool():
    from liveweb_arena.plugins.openlibrary.templates.author_engagement_extrema import ENGAGEMENT_AUTHOR_POOL as EX_POOL
    from liveweb_arena.plugins.openlibrary.templates.author_comparison import ENGAGEMENT_AUTHOR_POOL as CMP_POOL
    from liveweb_arena.plugins.openlibrary.templates.reading_stats_filter import ENGAGEMENT_AUTHOR_POOL as FLT_POOL
    assert EX_POOL is ENGAGEMENT_AUTHOR_POOL
    assert CMP_POOL is ENGAGEMENT_AUTHOR_POOL
    assert FLT_POOL is ENGAGEMENT_AUTHOR_POOL


def test_all_validation_info_values_are_serializable():
    templates = [
        OpenLibraryAuthorEngagementExtremaTemplate(),
        OpenLibraryAuthorComparisonTemplate(),
        OpenLibraryReadingStatsFilterTemplate(),
    ]
    for tmpl in templates:
        q = tmpl.generate(seed=1)
        for key, val in q.validation_info.items():
            assert isinstance(val, (str, int, float, bool, type(None))), (
                f"{tmpl.name}.validation_info['{key}'] = {type(val).__name__} "
                f"(not JSON-serializable)"
            )


# ── 9. Author pool invariants ─────────────────────────────────────────


def test_engagement_author_pool_size():
    assert len(ENGAGEMENT_AUTHOR_POOL) == 81, f"Expected 81 authors, got {len(ENGAGEMENT_AUTHOR_POOL)}"


def test_engagement_author_pool_no_duplicates():
    names = [name for name, _ in ENGAGEMENT_AUTHOR_POOL]
    queries = [query for _, query in ENGAGEMENT_AUTHOR_POOL]
    assert len(names) == len(set(names)), "Duplicate author names in ENGAGEMENT_AUTHOR_POOL"
    assert len(queries) == len(set(queries)), "Duplicate author queries in ENGAGEMENT_AUTHOR_POOL"


def test_extrema_highest_ratings_count_gt():
    """Verify GT works with ratings_count metric for highest extrema."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "ratings_count": 500},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "ratings_count": 200},
            {"key": "/works/OL3W", "rank": 3, "title": "Misery", "ratings_count": 300},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 3, "extrema": "highest", "metric": "ratings_count",
        "metric_label": "number of ratings",
    }))
    assert result.success is True
    assert result.value == "It"


def test_extrema_gt_succeeds_with_25_works():
    """Regression: work_count=25 must succeed when collector fetches ≥25 works."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    works = [{"key": f"/works/OL{i}W", "rank": i, "title": f"Book {i}",
              "want_to_read_count": 1000 - i * 10} for i in range(1, 26)]
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", works),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 25, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is True
    assert result.value == "Book 1"  # highest want_to_read_count = 990
