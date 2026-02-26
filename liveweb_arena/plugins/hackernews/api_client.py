"""Hacker News Firebase API client with rate limiting."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from liveweb_arena.plugins.base_client import APIFetchError, BaseAPIClient, RateLimiter, validate_api_response

logger = logging.getLogger(__name__)

CACHE_SOURCE = "hackernews"

# Firebase API base URL
HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsClient(BaseAPIClient):
    """
    Hacker News Firebase API client.

    Uses the official HN Firebase API:
    - /topstories.json - top story IDs
    - /newstories.json - new story IDs
    - /askstories.json - Ask HN story IDs
    - /showstories.json - Show HN story IDs
    - /jobstories.json - job story IDs
    - /item/{id}.json - item details (story, comment, etc.)
    - /user/{id}.json - user details
    """

    # Rate limit: 500ms between requests (HN API is quite permissive)
    _rate_limiter = RateLimiter(min_interval=0.5)

    @classmethod
    async def get(
        cls,
        endpoint: str,
        timeout: float = 15.0,
    ) -> Optional[Any]:
        """
        Make GET request to HN Firebase API.

        Args:
            endpoint: API endpoint (e.g., "/topstories.json")
            timeout: Request timeout in seconds

        Returns:
            JSON response or None on error
        """
        await cls._rate_limit()

        url = f"{HN_API_BASE}{endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status != 200:
                        logger.warning(f"HN API error: status={response.status} for {endpoint}")
                        return None
                    return await response.json()
        except Exception as e:
            logger.warning(f"HN API request failed for {endpoint}: {e}")
            return None

    @classmethod
    async def get_top_stories(cls, limit: int = 30) -> List[int]:
        """
        Get top story IDs.

        Args:
            limit: Maximum number of story IDs to return

        Returns:
            List of story IDs
        """
        data = await cls.get("/topstories.json")
        if data and isinstance(data, list):
            return data[:limit]
        return []

    @classmethod
    async def get_ask_stories(cls, limit: int = 30) -> List[int]:
        """Get Ask HN story IDs."""
        data = await cls.get("/askstories.json")
        if data and isinstance(data, list):
            return data[:limit]
        return []

    @classmethod
    async def get_show_stories(cls, limit: int = 30) -> List[int]:
        """Get Show HN story IDs."""
        data = await cls.get("/showstories.json")
        if data and isinstance(data, list):
            return data[:limit]
        return []

    @classmethod
    async def get_job_stories(cls, limit: int = 30) -> List[int]:
        """Get job story IDs."""
        data = await cls.get("/jobstories.json")
        if data and isinstance(data, list):
            return data[:limit]
        return []

    @classmethod
    async def get_item(cls, item_id: int) -> Optional[Dict[str, Any]]:
        """
        Get item details (story, comment, poll, etc.).

        Args:
            item_id: HN item ID

        Returns:
            Item data dict or None
        """
        data = await cls.get(f"/item/{item_id}.json")
        if data and isinstance(data, dict):
            return data
        return None

    @classmethod
    async def get_user(cls, username: str) -> Optional[Dict[str, Any]]:
        """
        Get user details.

        Args:
            username: HN username

        Returns:
            User data dict or None
        """
        data = await cls.get(f"/user/{username}.json")
        if data and isinstance(data, dict):
            return data
        return None

    @classmethod
    async def get_items_batch(cls, item_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """
        Fetch multiple items in parallel.

        Args:
            item_ids: List of item IDs to fetch

        Returns:
            Dict mapping item_id to item data
        """
        results = {}

        # Fetch in batches to avoid overwhelming the API
        batch_size = 10
        for i in range(0, len(item_ids), batch_size):
            batch = item_ids[i:i + batch_size]
            tasks = [cls.get_item(item_id) for item_id in batch]
            batch_results = await asyncio.gather(*tasks)

            for item_id, data in zip(batch, batch_results):
                if data:
                    results[item_id] = data

        return results


async def fetch_homepage_api_data(limit: int = 30) -> Dict[str, Any]:
    """
    Fetch API data for HN homepage (top stories).

    Returns homepage format:
    {
        "stories": {
            "<id>": {
                "id": <id>,
                "rank": <1-based>,
                "title": "...",
                "by": "author",
                "score": <int>,
                "descendants": <comment_count>,
                "url": "...",
                ...
            },
            ...
        }
    }
    """
    story_ids = await HackerNewsClient.get_top_stories(limit=limit)
    if not story_ids:
        raise APIFetchError("Failed to fetch top stories", source="hackernews")

    items = await HackerNewsClient.get_items_batch(story_ids)

    # Build stories dict with rank info
    stories = {}
    for rank, story_id in enumerate(story_ids, start=1):
        if story_id in items:
            story = items[story_id]
            story["rank"] = rank
            stories[str(story_id)] = story

    return {"stories": stories}


async def fetch_category_api_data(category: str, limit: int = 30) -> Dict[str, Any]:
    """
    Fetch API data for a category page (ask, show, jobs).

    Args:
        category: "ask", "show", or "jobs"
        limit: Maximum stories to fetch

    Returns:
        {
            "category": "<category>",
            "stories": {
                "<id>": {...},
                ...
            }
        }
    """
    if category == "ask":
        story_ids = await HackerNewsClient.get_ask_stories(limit=limit)
    elif category == "show":
        story_ids = await HackerNewsClient.get_show_stories(limit=limit)
    elif category == "jobs":
        story_ids = await HackerNewsClient.get_job_stories(limit=limit)
    else:
        raise APIFetchError(f"Unknown category: {category}", source="hackernews")

    if not story_ids:
        raise APIFetchError(f"Failed to fetch {category} stories", source="hackernews")

    items = await HackerNewsClient.get_items_batch(story_ids)

    # Build stories dict with rank info
    stories = {}
    for rank, story_id in enumerate(story_ids, start=1):
        if story_id in items:
            story = items[story_id]
            story["rank"] = rank
            stories[str(story_id)] = story

    return {"category": category, "stories": stories}


async def fetch_item_api_data(item_id: int) -> Dict[str, Any]:
    """
    Fetch API data for a story/item detail page.

    Args:
        item_id: HN item ID

    Returns:
        Item data with full details

    Raises:
        APIFetchError: If item not found
    """
    item = await HackerNewsClient.get_item(item_id)
    if not item:
        raise APIFetchError(f"Item {item_id} not found", source="hackernews")

    return item


async def fetch_user_api_data(username: str) -> Dict[str, Any]:
    """
    Fetch API data for a user page.

    Args:
        username: HN username

    Returns:
        {
            "user": {user_data},
            "submissions": [submission_ids]
        }

    Raises:
        APIFetchError: If user not found
    """
    user = await HackerNewsClient.get_user(username)
    if not user:
        raise APIFetchError(f"User {username} not found", source="hackernews")

    return {
        "user": user,
        "submissions": user.get("submitted", [])[:30],  # Limit to recent submissions
    }
