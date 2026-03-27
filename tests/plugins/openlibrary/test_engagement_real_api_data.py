"""End-to-end GT computation tests using REAL Open Library API data.

Data fetched live on March 26, 2026 via:
  curl "https://openlibrary.org/search.json?q=author%3A%22{author}%22&sort=editions&limit=10&fields=key,title,want_to_read_count,ratings_count,edition_count"

These tests verify CLAUDE.md §5 item 1: "GT must return a concrete value."
They inject real API response structure (field names, nesting, types) into the
GT collector and confirm each template computes a concrete answer.
"""

import asyncio
from typing import Any, Dict, List, Optional

from liveweb_arena.core.gt_collector import set_current_gt_collector
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


# ── Real API data (fetched March 26, 2026) ────────────────────────────

AGATHA_CHRISTIE_TOP10 = [
    {"key": "/works/OL472715W", "rank": 1, "title": "The Mysterious Affair at Styles", "ratings_count": 84, "want_to_read_count": 620},
    {"key": "/works/OL471789W", "rank": 2, "title": "The Secret Adversary", "ratings_count": 33, "want_to_read_count": 295},
    {"key": "/works/OL472073W", "rank": 3, "title": "Murder on the Links", "ratings_count": 22, "want_to_read_count": 340},
    {"key": "/works/OL471576W", "rank": 4, "title": "Murder on the Orient Express", "ratings_count": 116, "want_to_read_count": 1355},
    {"key": "/works/OL471932W", "rank": 5, "title": "The Murder of Roger Ackroyd", "ratings_count": 76, "want_to_read_count": 699},
    {"key": "/works/OL471940W", "rank": 6, "title": "Poirot investigates", "ratings_count": 16, "want_to_read_count": 290},
    {"key": "/works/OL471565W", "rank": 7, "title": "And Then There Were None", "ratings_count": 164, "want_to_read_count": 1728},
    {"key": "/works/OL472549W", "rank": 8, "title": "The Man in the Brown Suit", "ratings_count": 18, "want_to_read_count": 228},
    {"key": "/works/OL471724W", "rank": 9, "title": "Death on the Nile", "ratings_count": 24, "want_to_read_count": 677},
    {"key": "/works/OL471509W", "rank": 10, "title": "The A.B.C. Murders", "ratings_count": 59, "want_to_read_count": 1056},
]

STEPHEN_KING_TOP10 = [
    {"key": "/works/OL81626W", "rank": 1, "title": "Carrie", "ratings_count": 160, "want_to_read_count": 2341},
    {"key": "/works/OL81632W", "rank": 2, "title": "\u2018Salem\u2019s Lot", "ratings_count": 93, "want_to_read_count": 1349},
    {"key": "/works/OL81634W", "rank": 3, "title": "Misery", "ratings_count": 135, "want_to_read_count": 2504},
    {"key": "/works/OL81633W", "rank": 4, "title": "The Shining", "ratings_count": 273, "want_to_read_count": 2874},
    {"key": "/works/OL81613W", "rank": 5, "title": "It", "ratings_count": 488, "want_to_read_count": 10362},
    {"key": "/works/OL81628W", "rank": 6, "title": "The Gunslinger", "ratings_count": 62, "want_to_read_count": 1061},
    {"key": "/works/OL81631W", "rank": 7, "title": "Pet Sematary", "ratings_count": 171, "want_to_read_count": 2238},
    {"key": "/works/OL81629W", "rank": 8, "title": "The Green Mile", "ratings_count": 104, "want_to_read_count": 1378},
    {"key": "/works/OL81630W", "rank": 9, "title": "The Dead Zone", "ratings_count": 46, "want_to_read_count": 524},
    {"key": "/works/OL81618W", "rank": 10, "title": "The Stand", "ratings_count": 85, "want_to_read_count": 1184},
]

NEIL_GAIMAN_TOP10 = [
    {"key": "/works/OL679358W", "rank": 1, "title": "Coraline", "ratings_count": 196, "want_to_read_count": 2546},
    {"key": "/works/OL453936W", "rank": 2, "title": "Good Omens", "ratings_count": 87, "want_to_read_count": 1038},
    {"key": "/works/OL679360W", "rank": 3, "title": "American Gods", "ratings_count": 56, "want_to_read_count": 665},
    {"key": "/works/OL15833328W", "rank": 4, "title": "Stardust", "ratings_count": 81, "want_to_read_count": 427},
    {"key": "/works/OL16804661W", "rank": 5, "title": "The Ocean at the End of the Lane", "ratings_count": 114, "want_to_read_count": 417},
    {"key": "/works/OL679333W", "rank": 6, "title": "Neverwhere", "ratings_count": 122, "want_to_read_count": 297},
    {"key": "/works/OL679266W", "rank": 7, "title": "Anansi Boys", "ratings_count": 71, "want_to_read_count": 174},
    {"key": "/works/OL679348W", "rank": 8, "title": "The Graveyard Book", "ratings_count": 121, "want_to_read_count": 509},
    {"key": "/works/OL679359W", "rank": 9, "title": "Fragile Things", "ratings_count": 8, "want_to_read_count": 109},
    {"key": "/works/OL101948W", "rank": 10, "title": "The swords of Lankhmar", "ratings_count": 2, "want_to_read_count": 14},
]


def _christie_collected():
    return {
        "ol:search:christie": _make_search_entry(
            'author:"agatha christie"', "editions", AGATHA_CHRISTIE_TOP10,
        ),
    }


def _king_collected():
    return {
        "ol:search:king": _make_search_entry(
            'author:"stephen king"', "editions", STEPHEN_KING_TOP10,
        ),
    }


def _gaiman_collected():
    return {
        "ol:search:gaiman": _make_search_entry(
            'author:"neil gaiman"', "editions", NEIL_GAIMAN_TOP10,
        ),
    }


# ── T96: author_engagement_extrema with real data ─────────────────────


class TestT96RealData:
    """GT computation for T96 using real OL API data."""

    tmpl = OpenLibraryAuthorEngagementExtremaTemplate()

    def test_highest_want_to_read_top5_christie(self):
        result = _run_gt(_christie_collected(), self.tmpl.get_ground_truth({
            "author_name": "Agatha Christie",
            "author_query": "agatha christie",
            "search_query": 'author:"agatha christie"',
            "sort": "editions", "work_count": 5,
            "extrema": "highest", "metric": "want_to_read_count",
            "metric_label": "want-to-read count",
        }))
        assert result.success is True
        assert result.value == "Murder on the Orient Express"  # 1355

    def test_highest_ratings_count_top5_christie(self):
        result = _run_gt(_christie_collected(), self.tmpl.get_ground_truth({
            "author_name": "Agatha Christie",
            "author_query": "agatha christie",
            "search_query": 'author:"agatha christie"',
            "sort": "editions", "work_count": 5,
            "extrema": "highest", "metric": "ratings_count",
            "metric_label": "number of ratings",
        }))
        assert result.success is True
        assert result.value == "Murder on the Orient Express"  # 116

    def test_lowest_want_to_read_top5_king(self):
        result = _run_gt(_king_collected(), self.tmpl.get_ground_truth({
            "author_name": "Stephen King",
            "author_query": "stephen king",
            "search_query": 'author:"stephen king"',
            "sort": "editions", "work_count": 5,
            "extrema": "lowest", "metric": "want_to_read_count",
            "metric_label": "want-to-read count",
        }))
        assert result.success is True
        assert result.value == "\u2018Salem\u2019s Lot"  # 1349

    def test_highest_ratings_count_top3_gaiman(self):
        result = _run_gt(_gaiman_collected(), self.tmpl.get_ground_truth({
            "author_name": "Neil Gaiman",
            "author_query": "neil gaiman",
            "search_query": 'author:"neil gaiman"',
            "sort": "editions", "work_count": 3,
            "extrema": "highest", "metric": "ratings_count",
            "metric_label": "number of ratings",
        }))
        assert result.success is True
        assert result.value == "Coraline"  # 196

    def test_highest_want_to_read_top7_king(self):
        result = _run_gt(_king_collected(), self.tmpl.get_ground_truth({
            "author_name": "Stephen King",
            "author_query": "stephen king",
            "search_query": 'author:"stephen king"',
            "sort": "editions", "work_count": 7,
            "extrema": "highest", "metric": "want_to_read_count",
            "metric_label": "want-to-read count",
        }))
        assert result.success is True
        assert result.value == "It"  # 10362


# ── T97: author_comparison with real data ──────────────────────────────


class TestT97RealData:
    """GT computation for T97 using real OL API data."""

    tmpl = OpenLibraryAuthorComparisonTemplate()

    def test_want_to_read_difference_christie_vs_king_top5(self):
        collected = {**_christie_collected(), **_king_collected()}
        result = _run_gt(collected, self.tmpl.get_ground_truth({
            "author_a_name": "Agatha Christie",
            "author_a_query": "agatha christie",
            "search_query_a": 'author:"agatha christie"',
            "author_b_name": "Stephen King",
            "author_b_query": "stephen king",
            "search_query_b": 'author:"stephen king"',
            "sort": "editions", "work_count": 5,
            "metric": "want_to_read_count",
            "metric_label": "total want-to-read count",
        }))
        assert result.success is True
        # Christie top 5 wtr: 620+295+340+1355+699 = 3309
        # King top 5 wtr: 2341+1349+2504+2874+10362 = 19430
        assert result.value == str(abs(3309 - 19430))  # "16121"

    def test_ratings_count_difference_christie_vs_gaiman_top3(self):
        collected = {**_christie_collected(), **_gaiman_collected()}
        result = _run_gt(collected, self.tmpl.get_ground_truth({
            "author_a_name": "Agatha Christie",
            "author_a_query": "agatha christie",
            "search_query_a": 'author:"agatha christie"',
            "author_b_name": "Neil Gaiman",
            "author_b_query": "neil gaiman",
            "search_query_b": 'author:"neil gaiman"',
            "sort": "editions", "work_count": 3,
            "metric": "ratings_count",
            "metric_label": "total number of ratings",
        }))
        assert result.success is True
        # Christie top 3 rc: 84+33+22 = 139
        # Gaiman top 3 rc: 196+87+56 = 339
        assert result.value == str(abs(139 - 339))  # "200"

    def test_want_to_read_difference_king_vs_gaiman_top3(self):
        collected = {**_king_collected(), **_gaiman_collected()}
        result = _run_gt(collected, self.tmpl.get_ground_truth({
            "author_a_name": "Stephen King",
            "author_a_query": "stephen king",
            "search_query_a": 'author:"stephen king"',
            "author_b_name": "Neil Gaiman",
            "author_b_query": "neil gaiman",
            "search_query_b": 'author:"neil gaiman"',
            "sort": "editions", "work_count": 3,
            "metric": "want_to_read_count",
            "metric_label": "total want-to-read count",
        }))
        assert result.success is True
        # King top 3 wtr: 2341+1349+2504 = 6194
        # Gaiman top 3 wtr: 2546+1038+665 = 4249
        assert result.value == str(abs(6194 - 4249))  # "1945"


# ── T98: reading_stats_filter with real data ───────────────────────────


class TestT98RealData:
    """GT computation for T98 using real OL API data."""

    tmpl = OpenLibraryReadingStatsFilterTemplate()

    def test_want_to_read_above_500_top5_christie(self):
        result = _run_gt(_christie_collected(), self.tmpl.get_ground_truth({
            "author_name": "Agatha Christie",
            "author_query": "agatha christie",
            "search_query": 'author:"agatha christie"',
            "sort": "editions", "work_count": 5,
            "metric": "want_to_read_count",
            "metric_label": "people who want to read them",
            "threshold": 500,
        }))
        assert result.success is True
        # Styles=620>500 ✓, Adversary=295 ✗, Links=340 ✗, Orient=1355>500 ✓, Ackroyd=699>500 ✓
        assert result.value == "3"

    def test_ratings_count_above_50_top5_king(self):
        result = _run_gt(_king_collected(), self.tmpl.get_ground_truth({
            "author_name": "Stephen King",
            "author_query": "stephen king",
            "search_query": 'author:"stephen king"',
            "sort": "editions", "work_count": 5,
            "metric": "ratings_count",
            "metric_label": "ratings",
            "threshold": 50,
        }))
        assert result.success is True
        # Carrie=160>50 ✓, Salem=93>50 ✓, Misery=135>50 ✓, Shining=273>50 ✓, It=488>50 ✓
        assert result.value == "5"

    def test_want_to_read_above_1000_top10_gaiman(self):
        result = _run_gt(_gaiman_collected(), self.tmpl.get_ground_truth({
            "author_name": "Neil Gaiman",
            "author_query": "neil gaiman",
            "search_query": 'author:"neil gaiman"',
            "sort": "editions", "work_count": 10,
            "metric": "want_to_read_count",
            "metric_label": "people who want to read them",
            "threshold": 1000,
        }))
        assert result.success is True
        # Coraline=2546>1000 ✓, Good Omens=1038>1000 ✓, rest < 1000
        assert result.value == "2"

    def test_ratings_count_above_100_top5_gaiman(self):
        result = _run_gt(_gaiman_collected(), self.tmpl.get_ground_truth({
            "author_name": "Neil Gaiman",
            "author_query": "neil gaiman",
            "search_query": 'author:"neil gaiman"',
            "sort": "editions", "work_count": 5,
            "metric": "ratings_count",
            "metric_label": "ratings",
            "threshold": 100,
        }))
        assert result.success is True
        # Coraline=196>100 ✓, Good Omens=87 ✗, American Gods=56 ✗, Stardust=81 ✗, Ocean=114>100 ✓
        assert result.value == "2"
