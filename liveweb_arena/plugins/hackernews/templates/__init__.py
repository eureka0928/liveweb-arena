"""Hacker News question templates.

RL-friendly template design:
- All templates require multi-step reasoning
- All templates require computation or comparison
- All templates have large exploration space
- Low memorization risk due to dynamic data and combinatorial question space
"""

from .multi_condition_filter import HackerNewsMultiConditionFilterTemplate
from .extrema_comparison import HackerNewsExtremaComparisonTemplate
from .category_comparison import HackerNewsCategoryComparisonTemplate
from .news_summary import HackerNewsNewsSummaryTemplate
from .score_sum import HackerNewsScoreSumTemplate
from .age_range import HackerNewsAgeRangeTemplate
from .title_word_count import HackerNewsTitleWordCountTemplate
from .domain_count import HackerNewsDomainCountTemplate

__all__ = [
    "HackerNewsMultiConditionFilterTemplate",
    "HackerNewsExtremaComparisonTemplate",
    "HackerNewsCategoryComparisonTemplate",
    "HackerNewsNewsSummaryTemplate",
    "HackerNewsScoreSumTemplate",
    "HackerNewsAgeRangeTemplate",
    "HackerNewsTitleWordCountTemplate",
    "HackerNewsDomainCountTemplate",
]
