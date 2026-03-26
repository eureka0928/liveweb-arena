"""Tests for new Hacker News templates (score_sum, age_range, title_word_count, domain_count)."""

import asyncio
import time

import pytest

from liveweb_arena.core.gt_collector import GTCollector, GTSourceType, set_current_gt_collector
from liveweb_arena.core.task_registry import TaskRegistry
from liveweb_arena.core.validators.base import get_registered_templates
from liveweb_arena.plugins.base import SubTask
from liveweb_arena.plugins.hackernews.templates.score_sum import HackerNewsScoreSumTemplate
from liveweb_arena.plugins.hackernews.templates.age_range import HackerNewsAgeRangeTemplate
from liveweb_arena.plugins.hackernews.templates.title_word_count import HackerNewsTitleWordCountTemplate
from liveweb_arena.plugins.hackernews.templates.domain_count import HackerNewsDomainCountTemplate


@pytest.fixture
def collector():
    gt_collector = GTCollector(
        subtasks=[SubTask(plugin_name="hackernews", intent="test", validation_info={}, answer_tag="answer1")]
    )
    set_current_gt_collector(gt_collector)
    try:
        yield gt_collector
    finally:
        set_current_gt_collector(None)


def run_async(coro):
    return asyncio.run(coro)


def _seed_stories(collector, stories):
    """Inject fake homepage stories into the GT collector."""
    api_data = {"stories": {str(s["id"]): s for s in stories}}
    collector._merge_api_data("https://news.ycombinator.com/", api_data)


FAKE_STORIES = [
    {"id": 1001, "title": "Show HN: My new AI project", "by": "alice", "score": 200,
     "descendants": 45, "url": "https://github.com/alice/ai-project", "rank": 1,
     "time": int(time.time()) - 3600, "type": "story"},
    {"id": 1002, "title": "Rust is great", "by": "bob", "score": 150,
     "descendants": 30, "url": "https://blog.example.com/rust", "rank": 2,
     "time": int(time.time()) - 7200, "type": "story"},
    {"id": 1003, "title": "A very long title about something interesting in tech", "by": "carol",
     "score": 300, "descendants": 80, "url": "https://github.com/carol/thing", "rank": 3,
     "time": int(time.time()) - 14400, "type": "story"},
    {"id": 1004, "title": "Ask HN: Best books?", "by": "dave", "score": 50,
     "descendants": 120, "rank": 4,
     "time": int(time.time()) - 28800, "type": "story"},  # No URL (Ask HN)
    {"id": 1005, "title": "Short", "by": "eve", "score": 400,
     "descendants": 10, "url": "https://www.nytimes.com/2026/article", "rank": 5,
     "time": int(time.time()) - 43200, "type": "story"},
]


# ── Registration ──

def test_new_templates_registered():
    templates = get_registered_templates()
    for name in [
        "hackernews_score_sum",
        "hackernews_age_range",
        "hackernews_title_word_count",
        "hackernews_domain_count",
    ]:
        assert name in templates, f"{name} not registered"


def test_registry_ids():
    expected = {
        105: ("hackernews", "hackernews_score_sum"),
        106: ("hackernews", "hackernews_age_range"),
        107: ("hackernews", "hackernews_title_word_count"),
        108: ("hackernews", "hackernews_domain_count"),
    }
    for tid, info in expected.items():
        assert TaskRegistry.TEMPLATES[tid] == info

    TaskRegistry._ensure_initialized()
    assert (105,) in TaskRegistry._combinations


# ── Generation ──

@pytest.mark.parametrize("template_cls", [
    HackerNewsScoreSumTemplate,
    HackerNewsAgeRangeTemplate,
    HackerNewsTitleWordCountTemplate,
    HackerNewsDomainCountTemplate,
])
def test_generate_starts_at_hn_newest(template_cls):
    """Start URL is /newest, not homepage — forces navigation to ranked front page."""
    q = template_cls().generate(42)
    assert q.start_url == "https://news.ycombinator.com/newest"
    assert q.template_name == template_cls().name
    assert "story_count" in q.validation_info


def test_title_word_count_uses_jittered_threshold():
    tmpl = HackerNewsTitleWordCountTemplate()
    thresholds = set()
    for seed in range(100):
        q = tmpl.generate(seed)
        thresholds.add(q.validation_info["word_threshold"])
    # With jitter, should get more values than the 5 base thresholds
    assert len(thresholds) > 5


# ── GT Source ──

@pytest.mark.parametrize("template_cls", [
    HackerNewsScoreSumTemplate,
    HackerNewsAgeRangeTemplate,
    HackerNewsTitleWordCountTemplate,
    HackerNewsDomainCountTemplate,
])
def test_gt_source_is_page_only(template_cls):
    assert template_cls().get_gt_source() == GTSourceType.PAGE_ONLY


# ── GT: requires city visit ──

def test_score_sum_requires_visit():
    result = run_async(
        HackerNewsScoreSumTemplate().get_ground_truth({"story_count": 5})
    )
    assert result.success is False


# ── GT: score_sum ──

def test_score_sum_computes_correctly(collector):
    _seed_stories(collector, FAKE_STORIES)

    # Top 3: 200 + 150 + 300 = 650
    result = run_async(
        HackerNewsScoreSumTemplate().get_ground_truth({"story_count": 3})
    )
    assert result.success is True
    assert result.value == "650"

    # Top 5: 200 + 150 + 300 + 50 + 400 = 1100
    result5 = run_async(
        HackerNewsScoreSumTemplate().get_ground_truth({"story_count": 5})
    )
    assert result5.success is True
    assert result5.value == "1100"


# ── GT: age_range ──

def test_age_range_computes_correctly(collector):
    _seed_stories(collector, FAKE_STORIES)

    # Top 5: times span from -1h to -12h = 11 hours
    result = run_async(
        HackerNewsAgeRangeTemplate().get_ground_truth({"story_count": 5})
    )
    assert result.success is True
    assert result.value == "11"  # 43200 - 3600 = 39600s = 11h

    # Top 3: times span from -1h to -4h = 3 hours
    result3 = run_async(
        HackerNewsAgeRangeTemplate().get_ground_truth({"story_count": 3})
    )
    assert result3.success is True
    assert result3.value == "3"  # 14400 - 3600 = 10800s = 3h


# ── GT: title_word_count ──

def test_title_word_count_counts_correctly(collector):
    _seed_stories(collector, FAKE_STORIES)
    # Titles and word counts:
    # 1: "Show HN: My new AI project" = 6 words
    # 2: "Rust is great" = 3 words
    # 3: "A very long title about something interesting in tech" = 9 words
    # 4: "Ask HN: Best books?" = 4 words
    # 5: "Short" = 1 word

    # k=5 → titles with >5 words: #1 (6), #3 (9) = 2
    result = run_async(
        HackerNewsTitleWordCountTemplate().get_ground_truth(
            {"story_count": 5, "word_threshold": 5}
        )
    )
    assert result.success is True
    assert result.value == "2"

    # k=2 → titles with >2 words: #1 (6), #2 (3), #3 (9), #4 (4) = 4
    result2 = run_async(
        HackerNewsTitleWordCountTemplate().get_ground_truth(
            {"story_count": 5, "word_threshold": 2}
        )
    )
    assert result2.success is True
    assert result2.value == "4"


# ── GT: domain_count ──

def test_domain_count_counts_correctly(collector):
    _seed_stories(collector, FAKE_STORIES)
    # URLs:
    # 1: github.com
    # 2: blog.example.com
    # 3: github.com (duplicate!)
    # 4: no URL (Ask HN)
    # 5: nytimes.com (www stripped)
    # Distinct domains: github.com, blog.example.com, nytimes.com = 3

    result = run_async(
        HackerNewsDomainCountTemplate().get_ground_truth({"story_count": 5})
    )
    assert result.success is True
    assert result.value == "3"


def test_domain_count_top3_no_duplicates(collector):
    _seed_stories(collector, FAKE_STORIES)
    # Top 3 URLs: github.com, blog.example.com, github.com → 2 distinct
    result = run_async(
        HackerNewsDomainCountTemplate().get_ground_truth({"story_count": 3})
    )
    assert result.success is True
    assert result.value == "2"


# ── Not enough stories ──

def test_not_collected_when_insufficient_stories(collector):
    _seed_stories(collector, FAKE_STORIES[:2])  # Only 2 stories

    for tmpl_cls in [
        HackerNewsScoreSumTemplate,
        HackerNewsAgeRangeTemplate,
        HackerNewsTitleWordCountTemplate,
        HackerNewsDomainCountTemplate,
    ]:
        result = run_async(tmpl_cls().get_ground_truth({"story_count": 5}))
        assert result.success is False, f"{tmpl_cls.__name__} should fail with only 2 stories"
