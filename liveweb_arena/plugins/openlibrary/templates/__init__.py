"""Open Library question templates.

RL-friendly template design:
- All templates require search or navigation to find data
- Dynamic data prevents memorization (edition counts, ratings change)
- Large entity pool (millions of works across 50+ subjects)
"""

from .book_stats import OpenLibraryBookStatsTemplate
from .book_comparison import OpenLibraryBookComparisonTemplate
from .author_editions import OpenLibraryAuthorEditionsTemplate
from .subject_multi_condition import OpenLibrarySubjectMultiConditionTemplate
from .author_engagement_extrema import OpenLibraryAuthorEngagementExtremaTemplate
from .author_comparison import OpenLibraryAuthorComparisonTemplate
from .reading_stats_filter import OpenLibraryReadingStatsFilterTemplate

__all__ = [
    "OpenLibraryBookStatsTemplate",
    "OpenLibraryBookComparisonTemplate",
    "OpenLibraryAuthorEditionsTemplate",
    "OpenLibrarySubjectMultiConditionTemplate",
    "OpenLibraryAuthorEngagementExtremaTemplate",
    "OpenLibraryAuthorComparisonTemplate",
    "OpenLibraryReadingStatsFilterTemplate",
]
