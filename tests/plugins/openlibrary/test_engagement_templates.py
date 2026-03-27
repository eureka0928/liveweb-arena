"""Tests for Open Library engagement & comparison templates (part 1).

Covers:
1. Template registration and generation invariants
2. author_engagement_extrema GT behavior and edge cases
3. author_comparison GT behavior and edge cases

Part 2 (reading_stats_filter, helpers, registry, consistency) is in
test_engagement_filter_and_helpers.py.
"""

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from liveweb_arena.core.gt_collector import set_current_gt_collector
from liveweb_arena.core.validators.base import get_registered_templates
from liveweb_arena.plugins.openlibrary.templates.author_comparison import (
    OpenLibraryAuthorComparisonTemplate,
)
from liveweb_arena.plugins.openlibrary.templates.author_engagement_extrema import (
    OpenLibraryAuthorEngagementExtremaTemplate,
)
from liveweb_arena.plugins.openlibrary.templates.reading_stats_filter import (
    OpenLibraryReadingStatsFilterTemplate,
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


# ── 1. Template registration ──────────────────────────────────────────

SEEDS = [1, 42, 100, 999, 12345]


@pytest.mark.parametrize("name", [
    "openlibrary_author_engagement_extrema",
    "openlibrary_author_comparison",
    "openlibrary_reading_stats_filter",
])
def test_template_registered(name):
    templates = get_registered_templates()
    assert name in templates, f"template '{name}' not registered"


# ── 2. Generation invariants ──────────────────────────────────────────


@pytest.mark.parametrize("seed", SEEDS)
def test_engagement_extrema_generate(seed):
    q = OpenLibraryAuthorEngagementExtremaTemplate().generate(seed)
    assert q.question_text
    assert "openlibrary.org" in q.start_url
    assert q.template_name == "openlibrary_author_engagement_extrema"
    assert q.validation_info["extrema"] in {"highest", "lowest"}
    assert q.validation_info["metric"] in {
        "want_to_read_count", "ratings_count",
    }
    if q.validation_info["extrema"] == "lowest":
        assert q.validation_info["work_count"] in {3, 5, 7}
    elif q.validation_info["metric"] == "ratings_count":
        assert q.validation_info["work_count"] in {3, 5}
    else:
        assert q.validation_info["work_count"] in {3, 5, 7, 10, 15, 20, 25}
    assert "q=author%3A%22" in q.start_url
    assert "sort=editions" in q.start_url


@pytest.mark.parametrize("seed", SEEDS)
def test_author_comparison_generate(seed):
    q = OpenLibraryAuthorComparisonTemplate().generate(seed)
    assert q.question_text
    assert "openlibrary.org" in q.start_url
    assert q.template_name == "openlibrary_author_comparison"
    assert q.validation_info["author_a_name"] != q.validation_info["author_b_name"]
    assert q.validation_info["metric"] in {
        "want_to_read_count", "ratings_count",
    }
    assert q.validation_info["work_count"] in {3, 5}


@pytest.mark.parametrize("seed", SEEDS)
def test_reading_stats_filter_generate(seed):
    q = OpenLibraryReadingStatsFilterTemplate().generate(seed)
    assert q.question_text
    assert "openlibrary.org" in q.start_url
    assert q.template_name == "openlibrary_reading_stats_filter"
    assert q.validation_info["metric"] in {
        "want_to_read_count", "ratings_count",
    }
    if q.validation_info["metric"] == "ratings_count":
        assert q.validation_info["work_count"] in {5}
    else:
        assert q.validation_info["work_count"] in {5, 10, 15}
    assert isinstance(q.validation_info["threshold"], int)


def test_author_comparison_distinct_authors_all_seeds():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    for seed in range(1, 30):
        q = tmpl.generate(seed)
        assert q.validation_info["author_a_name"] != q.validation_info["author_b_name"], (
            f"seed={seed}: same author selected twice"
        )


def test_author_comparison_position_swap_occurs():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    pairs = set()
    for seed in range(1, 50):
        q = tmpl.generate(seed)
        pairs.add((q.validation_info["author_a_name"], q.validation_info["author_b_name"]))
    assert len(pairs) > 10, "Position bias: too few unique ordered pairs"


def test_extrema_lowest_excludes_ratings_count():
    """ratings_count is excluded from lowest extrema to avoid missing-as-zero bias."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    lowest_metrics = set()
    highest_metrics = set()
    for seed in range(200):
        q = tmpl.generate(seed)
        if q.validation_info["extrema"] == "lowest":
            lowest_metrics.add(q.validation_info["metric"])
        else:
            highest_metrics.add(q.validation_info["metric"])
    assert lowest_metrics == {"want_to_read_count"}, (
        f"lowest should only use want_to_read_count, got {lowest_metrics}"
    )
    assert "ratings_count" in highest_metrics, (
        "highest should include ratings_count"
    )


# ── 3. author_engagement_extrema GT behavior ──────────────────────────


def test_extrema_finds_highest_want_to_read():
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 10000},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 2000},
            {"key": "/works/OL3W", "rank": 3, "title": "Misery", "want_to_read_count": 2500},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Stephen King", "author_query": "stephen king",
        "search_query": 'author:"stephen king"', "sort": "editions",
        "work_count": 3, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is True
    assert result.value == "It"


def test_extrema_finds_lowest_want_to_read():
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:austen": _make_search_entry('author:"jane austen"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Sense and Sensibility", "want_to_read_count": 50},
            {"key": "/works/OL2W", "rank": 2, "title": "Pride and Prejudice", "want_to_read_count": 500},
            {"key": "/works/OL3W", "rank": 3, "title": "Emma", "want_to_read_count": 200},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Jane Austen", "author_query": "jane austen",
        "search_query": 'author:"jane austen"', "sort": "editions",
        "work_count": 3, "extrema": "lowest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is True
    assert result.value == "Sense and Sensibility"


def test_extrema_rejects_unsorted_data():
    """GT must require sort=editions; unsorted data should produce not_collected."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:austen": _make_search_entry("jane austen", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "Sense and Sensibility", "want_to_read_count": 50},
            {"key": "/works/OL2W", "rank": 2, "title": "Pride and Prejudice", "want_to_read_count": 500},
            {"key": "/works/OL3W", "rank": 3, "title": "Emma", "want_to_read_count": 200},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Jane Austen", "author_query": "jane austen",
        "search_query": 'author:"jane austen"', "sort": "editions",
        "work_count": 3, "extrema": "lowest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is False
    assert result.is_data_not_collected()


def test_extrema_tie_breaks_alphabetically():
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:dickens": _make_search_entry('author:"charles dickens"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Oliver Twist", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "David Copperfield", "want_to_read_count": 100},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Charles Dickens", "author_query": "charles dickens",
        "search_query": 'author:"charles dickens"', "sort": "editions",
        "work_count": 2, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is True
    assert result.value == "David Copperfield"  # alphabetically earlier


def test_extrema_not_collected_wrong_author():
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:dickens": _make_search_entry('author:"charles dickens"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "X", "want_to_read_count": 100},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Jane Austen", "author_query": "jane austen",
        "search_query": 'author:"jane austen"', "sort": "editions",
        "work_count": 3, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is False
    assert result.is_data_not_collected()


def test_extrema_missing_wtr_treated_as_zero():
    """OL API omits want_to_read_count when the value is zero; GT treats absent as 0."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:dickens": _make_search_entry('author:"charles dickens"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Oliver Twist", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "David Copperfield"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Charles Dickens", "author_query": "charles dickens",
        "search_query": 'author:"charles dickens"', "sort": "editions",
        "work_count": 2, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is True
    assert result.value == "Oliver Twist"  # 100 > 0 (missing wtr treated as 0)


def test_extrema_missing_ratings_count_fails_gt():
    """Missing ratings_count should cause GT failure (not default to 0)."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:dickens": _make_search_entry('author:"charles dickens"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Oliver Twist", "ratings_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "David Copperfield"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Charles Dickens", "author_query": "charles dickens",
        "search_query": 'author:"charles dickens"', "sort": "editions",
        "work_count": 2, "extrema": "highest", "metric": "ratings_count",
        "metric_label": "number of ratings",
    }))
    assert result.success is False


def test_extrema_non_numeric_metric_causes_gt_failure():
    """Non-null non-numeric metric values (e.g. 'N/A') should cause a GT fail,
    not be silently treated as 0 — this signals unexpected data."""
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    collected = {
        "ol:search:dickens": _make_search_entry('author:"charles dickens"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "Oliver Twist", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "David Copperfield", "want_to_read_count": "N/A"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_name": "Charles Dickens", "author_query": "charles dickens",
        "search_query": 'author:"charles dickens"', "sort": "editions",
        "work_count": 2, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is False


def test_extrema_no_collected_data():
    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()
    result = _run_gt({}, tmpl.get_ground_truth({
        "author_name": "X", "author_query": "x",
        "search_query": 'author:"x"', "sort": "editions",
        "work_count": 3, "extrema": "highest", "metric": "want_to_read_count",
        "metric_label": "want-to-read count",
    }))
    assert result.success is False


# ── 4. author_comparison GT behavior ──────────────────────────────────


def test_comparison_returns_absolute_difference():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 500},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 200},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles", "want_to_read_count": 100},
            {"key": "/works/OL4W", "rank": 2, "title": "Adversary", "want_to_read_count": 50},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_a_name": "Stephen King",
        "author_a_query": "stephen king",
        "search_query_a": 'author:"stephen king"',
        "author_b_name": "Agatha Christie",
        "author_b_query": "agatha christie",
        "search_query_b": 'author:"agatha christie"',
        "sort": "editions", "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "total want-to-read count",
    }))
    assert result.success is True
    assert result.value == "550"  # abs(700 - 150)


def test_comparison_difference_is_commutative():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 100},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 50},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles", "want_to_read_count": 800},
            {"key": "/works/OL4W", "rank": 2, "title": "Adversary", "want_to_read_count": 300},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_a_name": "Stephen King",
        "author_a_query": "stephen king",
        "search_query_a": 'author:"stephen king"',
        "author_b_name": "Agatha Christie",
        "author_b_query": "agatha christie",
        "search_query_b": 'author:"agatha christie"',
        "sort": "editions", "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "total want-to-read count",
    }))
    assert result.success is True
    assert result.value == "950"  # abs(150 - 1100)


def test_comparison_equal_totals_yield_zero_difference():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 300},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles", "want_to_read_count": 300},
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
    assert result.value == "0"


def test_comparison_rejects_unsorted_data():
    """GT must require sort=editions; unsorted data should produce not_collected."""
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry("stephen king", None, [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 500},
            {"key": "/works/OL2W", "rank": 2, "title": "Carrie", "want_to_read_count": 200},
        ]),
        "ol:search:christie": _make_search_entry("agatha christie", None, [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles", "want_to_read_count": 100},
            {"key": "/works/OL4W", "rank": 2, "title": "Adversary", "want_to_read_count": 50},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_a_name": "Stephen King",
        "author_a_query": "stephen king",
        "search_query_a": 'author:"stephen king"',
        "author_b_name": "Agatha Christie",
        "author_b_query": "agatha christie",
        "search_query_b": 'author:"agatha christie"',
        "sort": "editions", "work_count": 2, "metric": "want_to_read_count",
        "metric_label": "total want-to-read count",
    }))
    assert result.success is False
    assert result.is_data_not_collected()


def test_comparison_not_collected_missing_author():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 500},
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
    assert result.success is False
    assert result.is_data_not_collected()


def test_comparison_no_collected_data():
    tmpl = OpenLibraryAuthorComparisonTemplate()
    result = _run_gt({}, tmpl.get_ground_truth({
        "author_a_name": "A", "author_a_query": "a",
        "search_query_a": 'author:"a"',
        "author_b_name": "B", "author_b_query": "b",
        "search_query_b": 'author:"b"',
        "sort": "editions", "work_count": 1, "metric": "want_to_read_count",
        "metric_label": "x",
    }))
    assert result.success is False


def test_comparison_missing_wtr_treated_as_zero():
    """OL API omits want_to_read_count when the value is zero; GT treats absent as 0."""
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": 500},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles"},
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
    assert result.value == "500"  # abs(500 - 0)


def test_comparison_missing_ratings_count_fails_gt():
    """Missing ratings_count should cause GT failure (not default to 0)."""
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "ratings_count": 500},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
            {"key": "/works/OL3W", "rank": 1, "title": "Styles"},
        ]),
    }
    result = _run_gt(collected, tmpl.get_ground_truth({
        "author_a_name": "Stephen King",
        "author_a_query": "stephen king",
        "search_query_a": 'author:"stephen king"',
        "author_b_name": "Agatha Christie",
        "author_b_query": "agatha christie",
        "search_query_b": 'author:"agatha christie"',
        "sort": "editions", "work_count": 1, "metric": "ratings_count",
        "metric_label": "total number of ratings",
    }))
    assert result.success is False


def test_comparison_non_numeric_metric_causes_gt_failure():
    """Non-null non-numeric metric values should cause a GT fail via safe_metric_value."""
    tmpl = OpenLibraryAuthorComparisonTemplate()
    collected = {
        "ol:search:king": _make_search_entry('author:"stephen king"', "editions", [
            {"key": "/works/OL1W", "rank": 1, "title": "It", "want_to_read_count": "N/A"},
        ]),
        "ol:search:christie": _make_search_entry('author:"agatha christie"', "editions", [
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
    assert result.success is False
