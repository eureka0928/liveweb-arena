"""Shared helpers for Open Library templates."""

import re
from typing import Any, Dict, Iterator, Optional

from liveweb_arena.core.gt_collector import get_current_gt_collector


def normalize_text(value: str) -> str:
    """Normalize text for robust matching.

    Hyphens are converted to spaces so 'Catch-22' and 'Catch 22' normalize
    identically.
    """
    spaced = value.replace("-", " ")
    collapsed = " ".join(spaced.split())
    return "".join(ch.lower() for ch in collapsed if ch.isalnum() or ch == " ").strip()


def titles_match(expected: str, actual: str) -> bool:
    """Fuzzy title comparison resilient to punctuation and casing.

    Uses a length-ratio guard for substring matching: the shorter normalized
    string must be at least 85% of the longer one to qualify as a match.
    This prevents 'the road' from matching 'on the road'.
    """
    lhs = normalize_text(expected)
    rhs = normalize_text(actual)
    if not lhs or not rhs:
        return False
    if lhs == rhs:
        return True
    shorter, longer = (lhs, rhs) if len(lhs) <= len(rhs) else (rhs, lhs)
    if shorter not in longer:
        return False
    return len(shorter) / len(longer) >= 0.85


def parse_numeric(value: Any) -> Optional[float]:
    """Convert API values to float; returns None for non-numeric values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


_ZERO_DEFAULTABLE_METRICS = frozenset({"want_to_read_count"})


def safe_metric_value(work: Dict[str, Any], metric: str) -> float:
    """Read an engagement metric from a work dict.

    For metrics in ``_ZERO_DEFAULTABLE_METRICS`` (currently only
    ``want_to_read_count``), absent values are treated as ``0.0``
    because the OL API omits that field when no one has marked the
    book.  For all other metrics (e.g. ``ratings_count``), absence
    raises ``ValueError`` — the data is too sparse to assume zero
    is semantically correct.

    Non-null values that cannot be parsed as a number always raise
    ``ValueError`` so callers can surface a proper GT failure.
    """
    raw = work.get(metric)
    if raw is None:
        if metric in _ZERO_DEFAULTABLE_METRICS:
            return 0.0
        title = work.get("title", "<unknown>")
        raise ValueError(
            f"Missing '{metric}' for work '{title}'"
        )
    parsed = parse_numeric(raw)
    if parsed is None:
        title = work.get("title", "<unknown>")
        raise ValueError(
            f"Non-numeric '{metric}' value {raw!r} for work '{title}'"
        )
    return parsed


def get_collected_data() -> Optional[Dict[str, Dict[str, Any]]]:
    """Get collected API data for PAGE_ONLY templates."""
    collector = get_current_gt_collector()
    if collector is None:
        return None
    return collector.get_collected_api_data()


def find_search_entry(
    collected: Dict[str, Dict[str, Any]],
    *,
    query: str,
    sort: str,
) -> Optional[Dict[str, Any]]:
    """
    Find collected Open Library search data for a specific query and sort.

    Returns the most recent matching entry if multiple pages were visited.
    """
    target_query = query.strip().lower()
    matched: Optional[Dict[str, Any]] = None
    for key, entry in collected.items():
        if not key.startswith("ol:") or not isinstance(entry, dict):
            continue
        works = entry.get("works")
        if not isinstance(works, dict):
            continue
        entry_query = str(entry.get("query", "")).strip().lower()
        entry_sort = entry.get("sort")
        if entry_query == target_query and entry_sort == sort:
            matched = entry
    return matched


def iter_collected_works(collected: Dict[str, Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    """Iterate work-level records from collected Open Library data."""
    for entry in collected.values():
        if not isinstance(entry, dict):
            continue
        works = entry.get("works")
        if isinstance(works, dict):
            for work in works.values():
                if isinstance(work, dict):
                    yield work
            continue

        if "key" in entry and "title" in entry:
            yield entry


def normalize_author_fragment(value: str) -> str:
    """Normalize author text by stripping punctuation and collapsing whitespace."""
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def extract_author_filter(query: str) -> Optional[str]:
    """
    Extract normalized author text from author-filter queries.

    Accepts query forms like:
    - author:"mark twain"
    - AUTHOR: "Mark Twain"
    - author:'h.g. wells'

    Returns None if the query is not an author-filter query.
    """
    cleaned = query.strip().lower()
    if not cleaned:
        return None

    match = re.match(r"^author\s*:\s*(.+)$", cleaned)
    if not match:
        return None

    rhs = match.group(1).strip()
    if len(rhs) >= 2 and rhs[0] == rhs[-1] and rhs[0] in {'"', "'"}:
        rhs = rhs[1:-1].strip()

    normalized = normalize_author_fragment(rhs)
    return normalized or None


def find_author_search_entry(
    collected: Dict[str, Dict[str, Any]],
    *,
    search_query: str,
    sort: str,
    allow_unsorted_fallback: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Find search data for an author-filtered search query.

    The *search_query* passed by the template always uses ``author:"name"``
    syntax, but the agent may have typed a plain-text query like
    ``agatha christie`` instead.  To handle both cases the collected entry's
    query is first checked for ``author:`` syntax; if that is absent the
    raw query text is normalized and compared directly.

    By default, this matcher is strict about sort order. When
    ``allow_unsorted_fallback=True``, it first prefers an exact sort match and
    only falls back to entries with no sort parameter when no exact match was
    collected.
    """
    target_author = extract_author_filter(search_query)
    if not target_author:
        return None

    requested_sort = sort.strip()
    matched_exact: Optional[Dict[str, Any]] = None
    matched_unsorted: Optional[Dict[str, Any]] = None

    for key, entry in collected.items():
        if not key.startswith("ol:") or not isinstance(entry, dict):
            continue
        works = entry.get("works")
        if not isinstance(works, dict):
            continue

        entry_query = str(entry.get("query", ""))
        if not entry_query.strip():
            continue

        entry_author = extract_author_filter(entry_query)
        if entry_author is None:
            entry_author = normalize_author_fragment(entry_query)
        if entry_author != target_author:
            continue

        sort_value = entry.get("sort")
        entry_sort = str(sort_value).strip() if sort_value is not None else ""

        if entry_sort == requested_sort:
            matched_exact = entry
            continue

        if allow_unsorted_fallback and not entry_sort:
            matched_unsorted = entry

    return matched_exact if matched_exact is not None else matched_unsorted
