"""Shared helpers for Hacker News templates."""

from typing import Any, Dict, List, Optional, Tuple

from liveweb_arena.core.ground_truth_trigger import GroundTruthResult
from liveweb_arena.core.gt_collector import get_current_gt_collector

_SKIP_PREFIXES = ("user:", "hn_category:", "external:", "hn_external:")


def collect_homepage_stories(
    n: int,
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[GroundTruthResult]]:
    """Collect top-N homepage stories from GT data.

    Returns (stories_sorted_by_rank, None) on success,
    or (None, failure_result) on error.
    """
    gt_collector = get_current_gt_collector()
    if gt_collector is None:
        return None, GroundTruthResult.system_error("No GT collector")

    collected = gt_collector.get_collected_api_data()
    if not collected:
        return None, GroundTruthResult.not_collected("No HN data collected")

    stories = []
    for key, data in collected.items():
        if not isinstance(data, dict):
            continue
        if any(key.startswith(p) for p in _SKIP_PREFIXES):
            continue
        rank = data.get("rank")
        if rank is None or rank > n:
            continue
        stories.append(data)

    if len(stories) < n:
        available = sorted(s["rank"] for s in stories)
        return None, GroundTruthResult.not_collected(
            f"Only {len(stories)}/{n} stories collected. Ranks: {available}"
        )

    stories.sort(key=lambda s: s["rank"])
    return stories[:n], None
