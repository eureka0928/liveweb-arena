"""Focused tests for the ArXiv plugin and templates."""

import asyncio

import pytest

from liveweb_arena.core.gt_collector import GTCollector, GTSourceType, set_current_gt_collector
from liveweb_arena.core.task_registry import TaskRegistry
from liveweb_arena.core.validators.base import get_registered_templates
from liveweb_arena.plugins import get_all_plugins
from liveweb_arena.plugins.base import SubTask
from liveweb_arena.plugins.arxiv.arxiv import ArxivPlugin
from liveweb_arena.plugins.arxiv.api_client import parse_listing_html
from liveweb_arena.plugins.arxiv.templates.paper_info import ArxivPaperInfoTemplate
from liveweb_arena.plugins.arxiv.templates.author_extrema import ArxivAuthorExtremaTemplate
from liveweb_arena.plugins.arxiv.templates.multi_author_filter import ArxivMultiAuthorFilterTemplate
from liveweb_arena.plugins.arxiv.templates.title_length_extrema import ArxivTitleLengthExtremaTemplate
from liveweb_arena.plugins.arxiv.templates.category_comparison import ArxivCategoryComparisonTemplate
from liveweb_arena.plugins.arxiv.templates.variables import CATEGORIES, CATEGORY_PAIRS


@pytest.fixture
def collector():
    gt_collector = GTCollector(
        subtasks=[SubTask(plugin_name="arxiv", intent="test", validation_info={}, answer_tag="answer1")]
    )
    set_current_gt_collector(gt_collector)
    try:
        yield gt_collector
    finally:
        set_current_gt_collector(None)


def run_async(coro):
    return asyncio.run(coro)


# ---------- Plugin registration ----------


def test_plugin_and_templates_registered():
    assert "arxiv" in get_all_plugins()
    templates = get_registered_templates()
    for name in [
        "arxiv_paper_info",
        "arxiv_author_extrema",
        "arxiv_multi_author_filter",
        "arxiv_title_length_extrema",
        "arxiv_category_comparison",
    ]:
        assert name in templates


# ---------- Plugin URL extraction ----------


def test_extract_category_from_listing_urls():
    plugin = ArxivPlugin()
    # /new and /recent listings are matched
    assert plugin._extract_category("list/cs.AI/new") == "cs.AI"
    assert plugin._extract_category("list/hep-th/new") == "hep-th"
    # Hyphenated group with lowercase subcategory
    assert plugin._extract_category("list/cond-mat.str-el/new") == "cond-mat.str-el"
    # Hyphenated group with uppercase subcategory
    assert plugin._extract_category("list/astro-ph.CO/new") == "astro-ph.CO"
    # /recent also matches (GT always fetches /new data regardless)
    assert plugin._extract_category("list/cs.CV/recent") == "cs.CV"
    # Other modes are rejected (different paper sets)
    assert plugin._extract_category("list/math.CO/pastweek") == ""
    assert plugin._extract_category("list/stat.ML/2603") == ""
    # Invalid paths
    assert plugin._extract_category("abs/2603.16870v1") == ""
    assert plugin._extract_category("search/") == ""
    assert plugin._extract_category("") == ""


def test_needs_api_data_for_valid_urls():
    plugin = ArxivPlugin()
    assert plugin.needs_api_data("https://arxiv.org/list/cs.AI/new") is True
    # Abstract pages no longer trigger API fetch (no template reads abstract data)
    assert plugin.needs_api_data("https://arxiv.org/abs/2603.16870v1") is False
    # /recent also triggers GT collection (data always fetched from /new)
    assert plugin.needs_api_data("https://arxiv.org/list/cs.AI/recent") is True
    assert plugin.needs_api_data("https://arxiv.org/search/?query=llm") is False
    assert plugin.needs_api_data("https://arxiv.org/") is False


def test_blocked_patterns():
    plugin = ArxivPlugin()
    blocked = plugin.get_blocked_patterns()
    assert any("export.arxiv.org/api" in p for p in blocked)
    assert any("rss.arxiv.org" in p for p in blocked)


# ---------- HTML listing page parsing ----------


SAMPLE_LISTING_HTML = """<!DOCTYPE html>
<html>
<head><title>cs.AI new submissions</title></head>
<body>
<h3>Showing new listings for Thursday, 19 March 2026</h3>
<dl>
<dt>
  <a name='item1'>[1]</a>
  <a href="/abs/2603.17021" title="Abstract" id="2603.17021">arXiv:2603.17021</a>
  [<a href="/pdf/2603.17021">pdf</a>]
</dt>
<dd>
  <div class='meta'>
    <div class='list-title mathjax'><span class='descriptor'>Title:</span>
      Generative AI-assisted Participatory Modeling
    </div>
    <div class='list-authors'><a href="/search/cs?query=Pei,+Z">Zhihao Pei</a>, <a href="/search/cs?query=Lipovetzky,+N">Nir Lipovetzky</a>, <a href="/search/cs?query=Moallemi,+E+A">Enayat A. Moallemi</a></div>
    <div class='list-subjects'><span class='descriptor'>Subjects:</span>
      <span class="primary-subject">Artificial Intelligence (cs.AI)</span>
    </div>
    <p class='mathjax'>Abstract text here.</p>
  </div>
</dd>
<dt>
  <a name='item2'>[2]</a>
  <a href="/abs/2603.17063" title="Abstract" id="2603.17063">arXiv:2603.17063</a>
  [<a href="/pdf/2603.17063">pdf</a>]
</dt>
<dd>
  <div class='meta'>
    <div class='list-title mathjax'><span class='descriptor'>Title:</span>
      Neural Networks for Vision
    </div>
    <div class='list-authors'><a href="/search/cs?query=Smith,+A">Alice Smith</a>, <a href="/search/cs?query=Jones,+B">Bob Jones</a>, <a href="/search/cs?query=Lee,+C">Carol Lee</a></div>
    <div class='list-subjects'><span class='descriptor'>Subjects:</span>
      <span class="primary-subject">Computer Vision (cs.CV)</span>; Artificial Intelligence (cs.AI)
    </div>
    <p class='mathjax'>Another abstract.</p>
  </div>
</dd>
</dl>
<h3>Cross submissions (showing 1 of 1 entries)</h3>
<dl>
<dt>
  <a name='item3'>[3]</a>
  <a href="/abs/2603.18000" title="Abstract" id="2603.18000">arXiv:2603.18000</a>
</dt>
<dd>
  <div class='meta'>
    <div class='list-title mathjax'><span class='descriptor'>Title:</span>
      Cross-listed Paper Should Be Excluded
    </div>
    <div class='list-authors'><a href="/search/cs?query=Cross,+E">Eve Cross</a></div>
    <div class='list-subjects'><span class='descriptor'>Subjects:</span>
      <span class="primary-subject">Machine Learning (cs.LG)</span>; cs.AI
    </div>
  </div>
</dd>
</dl>
<h3>Replacement submissions (showing 0 of 0 entries)</h3>
</body>
</html>"""


def test_parse_listing_html_extracts_new_papers_only():
    papers = parse_listing_html(SAMPLE_LISTING_HTML)
    # Only new submissions (before Cross-lists section) are included
    assert len(papers) == 2
    assert papers[0]["arxiv_id"] == "2603.17021"
    assert papers[1]["arxiv_id"] == "2603.17063"


def test_parse_listing_html_extracts_metadata():
    papers = parse_listing_html(SAMPLE_LISTING_HTML)
    p1 = papers[0]
    assert p1["title"] == "Generative AI-assisted Participatory Modeling"
    assert p1["authors"] == ["Zhihao Pei", "Nir Lipovetzky", "Enayat A. Moallemi"]
    assert p1["primary_category"] == "cs.AI"

    p2 = papers[1]
    assert p2["title"] == "Neural Networks for Vision"
    assert p2["authors"] == ["Alice Smith", "Bob Jones", "Carol Lee"]
    assert p2["primary_category"] == "cs.CV"


def test_parse_listing_html_preserves_page_order():
    papers = parse_listing_html(SAMPLE_LISTING_HTML)
    ids = [p["arxiv_id"] for p in papers]
    assert ids == ["2603.17021", "2603.17063"]


def test_parse_listing_html_handles_empty_html():
    assert parse_listing_html("") == []
    assert parse_listing_html("<html></html>") == []


def test_parse_listing_html_handles_no_cross_lists():
    """Page with only new submissions and replacements (no cross-lists section)."""
    html = """
    <dl>
    <dt><a href="/abs/2603.10001">arXiv:2603.10001</a></dt>
    <dd>
      <div class='list-title mathjax'><span class='descriptor'>Title:</span>
        Only New Paper
      </div>
      <div class='list-authors'><a href="#">Author A</a></div>
      <div class='list-subjects'><span class='descriptor'>Subjects:</span>
        <span class="primary-subject">Artificial Intelligence (cs.AI)</span>
      </div>
    </dd>
    </dl>
    <h3>Replacement submissions (showing 1 of 1 entries)</h3>
    <dl>
    <dt><a href="/abs/2603.00001">arXiv:2603.00001</a></dt>
    <dd>
      <div class='list-title mathjax'><span class='descriptor'>Title:</span>
        Replaced Paper
      </div>
      <div class='list-authors'><a href="#">Author B</a></div>
      <div class='list-subjects'><span class='descriptor'>Subjects:</span>
        <span class="primary-subject">Artificial Intelligence (cs.AI)</span>
      </div>
    </dd>
    </dl>"""
    papers = parse_listing_html(html)
    assert len(papers) == 1
    assert papers[0]["title"] == "Only New Paper"


# ---------- GT collector merge logic ----------


def test_gt_collector_merges_arxiv_listing_data(collector):
    fake_listing_data = {
        "category": "cs.AI",
        "paper_count": 2,
        "papers": {
            "2603.00001v1": {
                "rank": 1,
                "arxiv_id": "2603.00001v1",
                "title": "Paper One",
                "authors": ["Author A"],
                "primary_category": "cs.AI",
                "categories": ["cs.AI"],
                "published": "2026-03-17T10:00:00Z",
                "summary": "Summary one.",
            },
            "2603.00002v1": {
                "rank": 2,
                "arxiv_id": "2603.00002v1",
                "title": "Paper Two",
                "authors": ["Author B", "Author C", "Author D"],
                "primary_category": "cs.AI",
                "categories": ["cs.AI", "cs.LG"],
                "published": "2026-03-17T09:00:00Z",
                "summary": "Summary two.",
            },
        },
    }

    result = collector._merge_api_data(
        "https://arxiv.org/list/cs.AI/new",
        fake_listing_data,
    )
    assert "+2 papers" in result
    assert "arxiv:cs.AI" in collector.get_collected_api_data()
    stored = collector.get_collected_api_data()["arxiv:cs.AI"]
    assert stored["paper_count"] == 2
    assert "2603.00001v1" in stored["papers"]


def test_gt_collector_does_not_overwrite_existing_listing(collector):
    """Second visit to same category listing should not overwrite first visit's data."""
    data1 = {
        "category": "cs.AI",
        "paper_count": 1,
        "papers": {"id1": {"rank": 1, "arxiv_id": "id1", "title": "First Visit",
                           "authors": ["A"], "primary_category": "cs.AI",
                           "categories": ["cs.AI"], "published": "", "summary": ""}},
    }
    data2 = {
        "category": "cs.AI",
        "paper_count": 1,
        "papers": {"id2": {"rank": 1, "arxiv_id": "id2", "title": "Second Visit",
                           "authors": ["B"], "primary_category": "cs.AI",
                           "categories": ["cs.AI"], "published": "", "summary": ""}},
    }
    result1 = collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data1)
    assert "+1 papers" in result1
    result2 = collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data2)
    assert "already have" in result2
    # First visit's data is preserved
    stored = collector.get_collected_api_data()["arxiv:cs.AI"]
    assert "id1" in stored["papers"]
    assert "id2" not in stored["papers"]


def test_gt_collector_collects_data_from_recent_url(collector):
    """Agent visiting /recent should still trigger GT collection (using /new data)."""
    data = {
        "category": "cs.AI",
        "paper_count": 1,
        "papers": {"id1": {"rank": 1, "arxiv_id": "id1", "title": "T",
                           "authors": ["A"], "primary_category": "cs.AI",
                           "categories": ["cs.AI"], "published": "", "summary": ""}},
    }
    result = collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)
    assert "+1 papers" in result
    assert "arxiv:cs.AI" in collector.get_collected_api_data()


def test_gt_collector_ignores_arxiv_data_without_category(collector):
    result = collector._merge_api_data(
        "https://arxiv.org/list/cs.AI/new",
        {"papers": {"id1": {}}, "paper_count": 1},
    )
    # No category field → should not store
    assert result is None


# ---------- Template: paper_info (EASY) ----------


def test_paper_info_generates_valid_question():
    tmpl = ArxivPaperInfoTemplate()
    q = tmpl.generate(seed=42)
    assert q.template_name == "arxiv_paper_info"
    assert "arxiv.org/list/" in q.start_url
    assert "/new" in q.start_url
    assert "category_code" in q.validation_info
    assert "metric_field" in q.validation_info
    assert "rank" in q.validation_info
    assert q.validation_info["rank"] in [1, 2, 3]
    assert q.expected_steps == 5
    # Question should mention "new submissions"
    assert "new" in q.question_text.lower()


def test_paper_info_different_seeds_produce_variety():
    tmpl = ArxivPaperInfoTemplate()
    questions = [tmpl.generate(seed=s) for s in range(20)]
    categories = {q.validation_info["category_code"] for q in questions}
    metrics = {q.validation_info["metric_field"] for q in questions}
    assert len(categories) > 1
    assert len(metrics) > 1


def test_paper_info_variant_selects_metric():
    tmpl = ArxivPaperInfoTemplate()
    q0 = tmpl.generate(seed=100, variant=0)
    q1 = tmpl.generate(seed=100, variant=1)
    assert q0.validation_info["metric_field"] != q1.validation_info["metric_field"]


def test_paper_info_gt_returns_author_count(collector):
    collector._merge_api_data(
        "https://arxiv.org/list/cs.AI/new",
        {
            "category": "cs.AI",
            "paper_count": 1,
            "papers": {
                "2603.00001v1": {
                    "rank": 1,
                    "arxiv_id": "2603.00001v1",
                    "title": "Paper One",
                    "authors": ["A", "B", "C"],
                    "primary_category": "cs.AI",
                    "categories": ["cs.AI"],
                    "published": "2026-03-17T10:00:00Z",
                    "summary": "S",
                },
            },
        },
    )

    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.AI", "metric_field": "author_count",
             "category_name": "Artificial Intelligence", "metric_label": "number of authors",
             "rank": 1}
        )
    )
    assert result.success is True
    assert result.value == "3"


def test_paper_info_gt_returns_title(collector):
    collector._merge_api_data(
        "https://arxiv.org/list/cs.CV/new",
        {
            "category": "cs.CV",
            "paper_count": 1,
            "papers": {
                "2603.00001v1": {
                    "rank": 1,
                    "arxiv_id": "2603.00001v1",
                    "title": "Neural Networks for Vision",
                    "authors": ["A"],
                    "primary_category": "cs.CV",
                    "categories": ["cs.CV", "cs.AI"],
                    "published": "2026-03-17T10:00:00Z",
                    "summary": "S",
                },
            },
        },
    )

    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.CV", "metric_field": "title",
             "category_name": "Computer Vision", "metric_label": "title",
             "rank": 1}
        )
    )
    assert result.success is True
    assert result.value == "Neural Networks for Vision"


def test_paper_info_gt_returns_second_paper_by_rank(collector):
    collector._merge_api_data(
        "https://arxiv.org/list/cs.AI/new",
        {
            "category": "cs.AI",
            "paper_count": 3,
            "papers": {
                "id1": {"rank": 1, "arxiv_id": "id1", "title": "First Paper",
                         "authors": ["A", "B"], "primary_category": "cs.AI",
                         "categories": ["cs.AI"], "published": "", "summary": ""},
                "id2": {"rank": 2, "arxiv_id": "id2", "title": "Second Paper",
                         "authors": ["C"], "primary_category": "cs.AI",
                         "categories": ["cs.AI"], "published": "", "summary": ""},
                "id3": {"rank": 3, "arxiv_id": "id3", "title": "Third Paper",
                         "authors": ["D", "E", "F"], "primary_category": "cs.AI",
                         "categories": ["cs.AI"], "published": "", "summary": ""},
            },
        },
    )

    # rank=2 should return second paper
    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.AI", "metric_field": "title",
             "category_name": "AI", "metric_label": "title", "rank": 2}
        )
    )
    assert result.success is True
    assert result.value == "Second Paper"

    # rank=3 author count
    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.AI", "metric_field": "author_count",
             "category_name": "AI", "metric_label": "author count", "rank": 3}
        )
    )
    assert result.success is True
    assert result.value == "3"


def test_paper_info_gt_system_error_when_no_collector():
    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.AI", "metric_field": "author_count",
             "category_name": "AI", "metric_label": "author count",
             "rank": 1}
        )
    )
    assert result.success is False
    assert result.is_system_error()


def test_paper_info_gt_fails_for_unknown_metric(collector):
    collector._merge_api_data(
        "https://arxiv.org/list/cs.AI/new",
        {
            "category": "cs.AI",
            "paper_count": 1,
            "papers": {
                "id1": {"rank": 1, "arxiv_id": "id1", "title": "T", "authors": ["A"],
                         "primary_category": "cs.AI", "categories": [], "published": "", "summary": ""},
            },
        },
    )
    result = run_async(
        ArxivPaperInfoTemplate().get_ground_truth(
            {"category_code": "cs.AI", "metric_field": "nonexistent",
             "category_name": "AI", "metric_label": "bad",
             "rank": 1}
        )
    )
    assert result.success is False


# ---------- Template: author_extrema (MEDIUM) ----------


def test_author_extrema_generates_valid_question():
    tmpl = ArxivAuthorExtremaTemplate()
    q = tmpl.generate(seed=42)
    assert q.template_name == "arxiv_author_extrema"
    assert "arxiv.org/list/" in q.start_url
    assert "category_code" in q.validation_info
    assert "is_most" in q.validation_info
    assert "top_n" in q.validation_info
    assert q.expected_steps == 7


def test_author_extrema_variant_toggles_extrema():
    tmpl = ArxivAuthorExtremaTemplate()
    q_even = tmpl.generate(seed=100, variant=0)
    q_odd = tmpl.generate(seed=100, variant=1)
    assert q_even.validation_info["is_most"] is True
    assert q_odd.validation_info["is_most"] is False


def _make_listing_data(category, papers_list):
    """Helper: build listing data dict from a list of (title, authors) tuples."""
    papers = {}
    for rank, (title, authors) in enumerate(papers_list, start=1):
        aid = f"2603.{10000 + rank}v1"
        papers[aid] = {
            "rank": rank,
            "arxiv_id": aid,
            "title": title,
            "authors": authors,
            "primary_category": category,
            "categories": [category],
            "published": "2026-03-17T10:00:00Z",
            "summary": f"Summary of {title}.",
        }
    return {
        "category": category,
        "paper_count": len(papers),
        "papers": papers,
    }


def test_author_extrema_finds_paper_with_most_authors(collector):
    data = _make_listing_data("cs.AI", [
        ("Paper A", ["Author1"]),
        ("Paper B", ["Author1", "Author2", "Author3", "Author4", "Author5"]),
        ("Paper C", ["Author1", "Author2"]),
        ("Paper D", ["Author1", "Author2", "Author3"]),
        ("Paper E", ["Author1", "Author2"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivAuthorExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_most": True, "top_n": 5}
        )
    )
    assert result.success is True
    assert "Paper B" in result.value
    assert "5 authors" in result.value


def test_author_extrema_finds_paper_with_fewest_authors(collector):
    data = _make_listing_data("cs.AI", [
        ("Paper A", ["Author1", "Author2", "Author3"]),
        ("Paper B", ["Author1"]),
        ("Paper C", ["Author1", "Author2"]),
        ("Paper D", ["Author1", "Author2", "Author3", "Author4"]),
        ("Paper E", ["Author1", "Author2"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivAuthorExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_most": False, "top_n": 5}
        )
    )
    assert result.success is True
    assert "Paper B" in result.value
    assert "1 authors" in result.value


def test_author_extrema_respects_top_n_limit(collector):
    data = _make_listing_data("cs.AI", [
        ("Paper A", ["Author1", "Author2"]),
        ("Paper B", ["Author1"]),
        ("Paper C", ["Author1", "Author2", "Author3"]),
        ("Paper D", ["Author1", "Author2", "Author3", "Author4", "Author5", "Author6"]),
        ("Paper E", ["Author1", "Author2"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    # top_n=3 should only look at first 3 papers, so Paper D (rank 4) is excluded
    result = run_async(
        ArxivAuthorExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_most": True, "top_n": 3}
        )
    )
    assert result.success is True
    assert "Paper C" in result.value  # 3 authors, best among top 3


def test_author_extrema_gt_system_error_when_no_collector():
    result = run_async(
        ArxivAuthorExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_most": True, "top_n": 5}
        )
    )
    assert result.success is False
    assert result.is_system_error()


def test_author_extrema_gt_fails_when_too_few_papers(collector):
    # Only 3 papers but top_n=5 — system error, not agent's fault
    data = _make_listing_data("cs.AI", [
        ("Paper A", ["Author1"]),
        ("Paper B", ["Author1", "Author2"]),
        ("Paper C", ["Author1", "Author2", "Author3"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivAuthorExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_most": True, "top_n": 5}
        )
    )
    assert result.success is False
    assert result.is_system_error()
    assert "only 3 papers" in result.error.lower()


# ---------- Template: category_comparison (HARD) ----------


def test_category_comparison_generates_valid_question():
    tmpl = ArxivCategoryComparisonTemplate()
    q = tmpl.generate(seed=42)
    assert q.template_name == "arxiv_category_comparison"
    assert "arxiv.org/list/" in q.start_url
    assert "cat1_code" in q.validation_info
    assert "cat2_code" in q.validation_info
    assert "cat2_url" in q.validation_info
    assert "top_n" in q.validation_info
    assert q.expected_steps == 9
    # Question should mention author counts, not raw paper counts
    assert "author" in q.question_text.lower()


def test_category_comparison_uses_cross_group_pairs():
    tmpl = ArxivCategoryComparisonTemplate()
    q = tmpl.generate(seed=42)
    cat1 = q.validation_info["cat1_code"]
    cat2 = q.validation_info["cat2_code"]
    # Categories should be from different groups
    group1 = cat1.split(".")[0] if "." in cat1 else cat1.split("-")[0]
    group2 = cat2.split(".")[0] if "." in cat2 else cat2.split("-")[0]
    assert group1 != group2


def test_category_comparison_computes_author_total_difference(collector):
    data1 = _make_listing_data("cs.AI", [
        ("P1", ["A1", "A2", "A3"]),
        ("P2", ["B1"]),
        ("P3", ["C1", "C2"]),
        ("P4", ["D1"]),
        ("P5", ["E1", "E2"]),
    ])
    data2 = _make_listing_data("math.CO", [
        ("Q1", ["X1", "X2"]),
        ("Q2", ["Y1", "Y2", "Y3", "Y4"]),
        ("Q3", ["Z1"]),
        ("Q4", ["W1", "W2"]),
        ("Q5", ["V1"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data1)
    collector._merge_api_data("https://arxiv.org/list/math.CO/new", data2)

    result = run_async(
        ArxivCategoryComparisonTemplate().get_ground_truth(
            {
                "cat1_code": "cs.AI",
                "cat1_name": "Artificial Intelligence",
                "cat2_code": "math.CO",
                "cat2_name": "Combinatorics",
                "top_n": 5,
            }
        )
    )
    assert result.success is True
    # cs.AI: 3+1+2+1+2=9, math.CO: 2+4+1+2+1=10, diff=-1
    assert "-1" in result.value
    assert "Artificial Intelligence: 9 authors" in result.value
    assert "Combinatorics: 10 authors" in result.value


def test_category_comparison_respects_top_n_window(collector):
    # 5 papers each, but top_n=3 should only use first 3
    data1 = _make_listing_data("cs.AI", [
        ("P1", ["A1", "A2"]),       # 2
        ("P2", ["B1"]),              # 1
        ("P3", ["C1", "C2", "C3"]), # 3  — total top-3: 6
        ("P4", ["D1"] * 10),         # 10 — excluded by top_n=3
        ("P5", ["E1"] * 10),         # 10 — excluded
    ])
    data2 = _make_listing_data("math.CO", [
        ("Q1", ["X1"]),              # 1
        ("Q2", ["Y1", "Y2"]),       # 2
        ("Q3", ["Z1"]),              # 1  — total top-3: 4
        ("Q4", ["W1"] * 10),         # excluded
        ("Q5", ["V1"] * 10),         # excluded
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data1)
    collector._merge_api_data("https://arxiv.org/list/math.CO/new", data2)

    result = run_async(
        ArxivCategoryComparisonTemplate().get_ground_truth(
            {
                "cat1_code": "cs.AI",
                "cat1_name": "AI",
                "cat2_code": "math.CO",
                "cat2_name": "Combinatorics",
                "top_n": 3,
            }
        )
    )
    assert result.success is True
    # top-3: cs.AI=6, math.CO=4, diff=2
    assert "2" in result.value
    assert "AI: 6 authors" in result.value


def test_category_comparison_gt_fails_when_one_category_missing(collector):
    data1 = _make_listing_data("cs.AI", [(f"P{i}", ["A1"]) for i in range(6)])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data1)

    result = run_async(
        ArxivCategoryComparisonTemplate().get_ground_truth(
            {
                "cat1_code": "cs.AI",
                "cat1_name": "AI",
                "cat2_code": "math.CO",
                "cat2_name": "Combinatorics",
                "top_n": 5,
            }
        )
    )
    assert result.success is False
    assert result.is_data_not_collected()


def test_category_comparison_gt_fails_when_too_few_papers(collector):
    # cat1 has enough, cat2 has only 2 but top_n=5 — system error, not agent's fault
    data1 = _make_listing_data("cs.AI", [(f"P{i}", ["A1"]) for i in range(6)])
    data2 = _make_listing_data("math.CO", [("Q1", ["X1"]), ("Q2", ["X2"])])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data1)
    collector._merge_api_data("https://arxiv.org/list/math.CO/new", data2)

    result = run_async(
        ArxivCategoryComparisonTemplate().get_ground_truth(
            {
                "cat1_code": "cs.AI",
                "cat1_name": "AI",
                "cat2_code": "math.CO",
                "cat2_name": "Combinatorics",
                "top_n": 5,
            }
        )
    )
    assert result.success is False
    assert result.is_system_error()
    assert "only 2 papers" in result.error.lower()


# ---------- Template: multi_author_filter (MEDIUM) ----------


def test_multi_author_filter_generates_valid_question():
    tmpl = ArxivMultiAuthorFilterTemplate()
    q = tmpl.generate(seed=42)
    assert q.template_name == "arxiv_multi_author_filter"
    assert "arxiv.org/list/" in q.start_url
    assert "top_n" in q.validation_info
    assert "threshold" in q.validation_info
    assert q.validation_info["top_n"] in [3, 4, 5]
    assert q.validation_info["threshold"] in [1, 2, 3]


def test_multi_author_filter_counts_correctly(collector):
    data = _make_listing_data("cs.AI", [
        ("P1", ["A1", "A2", "A3"]),      # 3 authors — > 2 ✓
        ("P2", ["B1"]),                    # 1 author  — > 2 ✗
        ("P3", ["C1", "C2", "C3", "C4"]), # 4 authors — > 2 ✓
        ("P4", ["D1", "D2"]),             # 2 authors — > 2 ✗
        ("P5", ["E1", "E2", "E3"]),       # 3 authors — > 2 ✓
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivMultiAuthorFilterTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "top_n": 5, "threshold": 2}
        )
    )
    assert result.success is True
    assert result.value == "3"  # P1, P3, P5 have >2 authors


def test_multi_author_filter_respects_top_n(collector):
    data = _make_listing_data("cs.AI", [
        ("P1", ["A1"]),                    # 1 — > 1 ✗
        ("P2", ["B1", "B2", "B3"]),       # 3 — > 1 ✓
        ("P3", ["C1", "C2"]),             # 2 — > 1 ✓
        ("P4", ["D1", "D2", "D3", "D4"]), # 4 — excluded by top_n=3
        ("P5", ["E1", "E2", "E3"]),       # 3 — excluded by top_n=3
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivMultiAuthorFilterTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "top_n": 3, "threshold": 1}
        )
    )
    assert result.success is True
    assert result.value == "2"  # P2 (3>1) and P3 (2>1) within top 3


def test_multi_author_filter_gt_system_error_when_too_few_papers(collector):
    data = _make_listing_data("cs.AI", [("P1", ["A1"]), ("P2", ["B1"])])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivMultiAuthorFilterTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "top_n": 5, "threshold": 2}
        )
    )
    assert result.success is False
    assert result.is_system_error()


def test_multi_author_filter_threshold_boundary(collector):
    # All papers have exactly 2 authors; threshold=2 means >2, so count=0
    data = _make_listing_data("cs.AI", [
        (f"P{i}", ["A1", "A2"]) for i in range(5)
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivMultiAuthorFilterTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "top_n": 5, "threshold": 2}
        )
    )
    assert result.success is True
    assert result.value == "0"  # strictly greater than, not >=


# ---------- Template: title_length_extrema (MEDIUM) ----------


def test_title_length_extrema_generates_valid_question():
    tmpl = ArxivTitleLengthExtremaTemplate()
    q = tmpl.generate(seed=42)
    assert q.template_name == "arxiv_title_length_extrema"
    assert "arxiv.org/list/" in q.start_url
    assert "is_longest" in q.validation_info
    assert "top_n" in q.validation_info
    assert q.validation_info["top_n"] in [3, 4, 5]


def test_title_length_extrema_finds_longest(collector):
    data = _make_listing_data("cs.AI", [
        ("Short", ["A1"]),
        ("A Much Longer Title Than The Others", ["B1"]),
        ("Medium Length", ["C1"]),
        ("Tiny", ["D1"]),
        ("Another Paper", ["E1"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivTitleLengthExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_longest": True, "top_n": 5}
        )
    )
    assert result.success is True
    assert "A Much Longer Title Than The Others" in result.value


def test_title_length_extrema_finds_shortest(collector):
    data = _make_listing_data("cs.AI", [
        ("Short", ["A1"]),
        ("A Much Longer Title Than The Others", ["B1"]),
        ("Medium Length", ["C1"]),
        ("Tiny", ["D1"]),
        ("Another Paper", ["E1"]),
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivTitleLengthExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_longest": False, "top_n": 5}
        )
    )
    assert result.success is True
    assert "Tiny" in result.value


def test_title_length_extrema_respects_top_n(collector):
    data = _make_listing_data("cs.AI", [
        ("Short", ["A1"]),
        ("Medium Length Title", ["B1"]),
        ("Longer Title Here", ["C1"]),
        ("X", ["D1"]),           # rank 4 — excluded by top_n=3
        ("Very Very Very Long Title Indeed", ["E1"]),  # rank 5 — excluded
    ])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivTitleLengthExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_longest": True, "top_n": 3}
        )
    )
    assert result.success is True
    assert "Medium Length Title" in result.value  # longest among top 3


def test_title_length_extrema_gt_system_error_when_too_few_papers(collector):
    data = _make_listing_data("cs.AI", [("P1", ["A1"]), ("P2", ["B1"])])
    collector._merge_api_data("https://arxiv.org/list/cs.AI/new", data)

    result = run_async(
        ArxivTitleLengthExtremaTemplate().get_ground_truth(
            {"category_code": "cs.AI", "category_name": "AI", "is_longest": True, "top_n": 5}
        )
    )
    assert result.success is False
    assert result.is_system_error()


# ---------- Task registry ----------


def test_registry_contains_arxiv_templates():
    expected = {
        90: ("arxiv", "arxiv_paper_info"),
        91: ("arxiv", "arxiv_author_extrema"),
        92: ("arxiv", "arxiv_category_comparison"),
        94: ("arxiv", "arxiv_multi_author_filter"),
        95: ("arxiv", "arxiv_title_length_extrema"),
    }
    for template_id, template_info in expected.items():
        assert TaskRegistry.TEMPLATES[template_id] == template_info

    TaskRegistry._ensure_initialized()
    assert (90,) in TaskRegistry._combinations


def test_arxiv_template_ids_in_version_6():
    assert [90, 91, 92, 94, 95] in TaskRegistry.TEMPLATE_VERSIONS


# ---------- Variables ----------


def test_category_pool_has_no_duplicates():
    codes = [c.code for c in CATEGORIES]
    assert len(codes) == len(set(codes))


def test_category_pairs_are_cross_group():
    for cat1, cat2 in CATEGORY_PAIRS:
        assert cat1.group != cat2.group


def test_all_categories_have_valid_listing_urls():
    for cat in CATEGORIES:
        url = cat.listing_url
        assert url.startswith("https://arxiv.org/list/")
        assert "/new" in url


# ---------- GT source type ----------


def test_arxiv_templates_expose_page_only_gt_source():
    assert ArxivPaperInfoTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert ArxivAuthorExtremaTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert ArxivMultiAuthorFilterTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert ArxivTitleLengthExtremaTemplate().get_gt_source() == GTSourceType.PAGE_ONLY
    assert ArxivCategoryComparisonTemplate().get_gt_source() == GTSourceType.PAGE_ONLY


# ---------- Validation rules ----------


def test_paper_info_validation_rules_include_metric_context():
    tmpl = ArxivPaperInfoTemplate()
    rules = tmpl.get_validation_rules({
        "category_name": "Artificial Intelligence",
        "metric_field": "author_count",
        "metric_label": "number of authors",
        "rank": 1,
    })
    assert "Artificial Intelligence" in rules
    assert "number of authors" in rules
    assert "1.0" in rules


def test_category_comparison_validation_rules_include_categories():
    tmpl = ArxivCategoryComparisonTemplate()
    rules = tmpl.get_validation_rules({
        "cat1_name": "Artificial Intelligence",
        "cat2_name": "Combinatorics",
        "top_n": 5,
    })
    assert "Artificial Intelligence" in rules
    assert "Combinatorics" in rules
    assert "author" in rules.lower()
    assert "5" in rules


def test_multi_author_filter_validation_rules():
    tmpl = ArxivMultiAuthorFilterTemplate()
    rules = tmpl.get_validation_rules({
        "category_name": "Robotics", "top_n": 5, "threshold": 3,
    })
    assert "Robotics" in rules
    assert "3" in rules
    assert "5" in rules
    assert "more than" in rules.lower()


def test_title_length_extrema_validation_rules():
    tmpl = ArxivTitleLengthExtremaTemplate()
    rules_longest = tmpl.get_validation_rules({
        "category_name": "AI", "is_longest": True, "top_n": 5,
    })
    assert "longest" in rules_longest
    rules_shortest = tmpl.get_validation_rules({
        "category_name": "AI", "is_longest": False, "top_n": 3,
    })
    assert "shortest" in rules_shortest
    assert "3" in rules_shortest


def test_author_extrema_validation_rules_include_extrema_type():
    tmpl = ArxivAuthorExtremaTemplate()
    rules_most = tmpl.get_validation_rules({
        "category_name": "AI", "is_most": True, "top_n": 5,
    })
    assert "most" in rules_most
    rules_fewest = tmpl.get_validation_rules({
        "category_name": "AI", "is_most": False, "top_n": 5,
    })
    assert "fewest" in rules_fewest
    assert "5" in rules_fewest
