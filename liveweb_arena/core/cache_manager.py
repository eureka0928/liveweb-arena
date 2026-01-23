"""
Cache Manager - Unified caching system for web pages and API data.

Design Principles:
1. SNAPSHOT CONSISTENCY - All data in a snapshot is from the same time point
2. ATOMIC REFRESH - Web pages and API data refresh together
3. VERSION ISOLATION - Each evaluation uses a fixed snapshot version
4. MULTI-PROCESS SAFE - File locks prevent concurrent write conflicts
5. PERSISTENT STORAGE - File-based cache survives restarts
"""

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    """Configuration for a cache source."""
    ttl: int = 300              # Time-to-live in seconds
    max_versions: int = 3       # Maximum snapshot versions to keep
    preload: bool = True        # Whether to preload before evaluation


# Default cache configurations
DEFAULT_CACHE_CONFIGS: Dict[str, CacheConfig] = {
    "coingecko": CacheConfig(ttl=300, max_versions=3, preload=True),
    "stooq": CacheConfig(ttl=300, max_versions=3, preload=True),
    "tmdb": CacheConfig(ttl=86400, max_versions=2, preload=False),
    "weather": CacheConfig(ttl=1800, max_versions=2, preload=False),
    "taostats": CacheConfig(ttl=300, max_versions=2, preload=False),
}


@dataclass
class SnapshotMetadata:
    """Metadata for a cache snapshot."""
    version: int
    timestamp: float
    source: str
    ttl: int
    page_keys: List[str] = field(default_factory=list)
    api_keys: List[str] = field(default_factory=list)

    def is_expired(self) -> bool:
        """Check if this snapshot has expired."""
        return time.time() - self.timestamp > self.ttl

    def age_seconds(self) -> float:
        """Return age of snapshot in seconds."""
        return time.time() - self.timestamp

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "source": self.source,
            "ttl": self.ttl,
            "page_keys": self.page_keys,
            "api_keys": self.api_keys,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SnapshotMetadata":
        return cls(
            version=data["version"],
            timestamp=data["timestamp"],
            source=data["source"],
            ttl=data["ttl"],
            page_keys=data.get("page_keys", []),
            api_keys=data.get("api_keys", []),
        )


class FileLockManager:
    """Manages file-based locks for multi-process safety."""

    def __init__(self, lock_dir: Path):
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._locks: Dict[str, Any] = {}

    def _get_lock_path(self, source: str) -> Path:
        return self.lock_dir / f"{source}.lock"

    @contextmanager
    def read_lock(self, source: str):
        """Acquire a shared read lock."""
        lock_path = self._get_lock_path(source)
        lock_path.touch(exist_ok=True)

        with open(lock_path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def write_lock(self, source: str):
        """Acquire an exclusive write lock."""
        lock_path = self._get_lock_path(source)
        lock_path.touch(exist_ok=True)

        with open(lock_path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class CacheManager:
    """
    Unified cache manager for web pages and API data.

    Key features:
    - Snapshot-based versioning ensures consistency
    - Atomic refresh of web + API data
    - Multi-process safe via file locks
    - Persistent file-based storage

    Usage:
        cache = CacheManager()

        # Get or refresh cache for a source
        version = cache.ensure_fresh("coingecko")

        # Read cached page
        html = cache.get_page("coingecko", "https://coingecko.com/en/coins/bitcoin", version)

        # Read cached API data
        data = cache.get_api_data("coingecko", "bitcoin_price", version)
    """

    def __init__(
        self,
        cache_dir: str = "cache",
        configs: Dict[str, CacheConfig] = None,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.configs = configs or DEFAULT_CACHE_CONFIGS.copy()
        self.lock_manager = FileLockManager(self.cache_dir / "locks")

        # In-memory cache of metadata for performance
        self._metadata_cache: Dict[str, SnapshotMetadata] = {}

        # Registered data fetchers
        self._page_fetchers: Dict[str, Callable] = {}
        self._api_fetchers: Dict[str, Callable] = {}

    def register_fetcher(
        self,
        source: str,
        page_fetcher: Callable = None,
        api_fetcher: Callable = None,
    ):
        """
        Register data fetchers for a source.

        Args:
            source: Cache source name (e.g., "coingecko")
            page_fetcher: Async function to fetch web pages
            api_fetcher: Async function to fetch API data
        """
        if page_fetcher:
            self._page_fetchers[source] = page_fetcher
        if api_fetcher:
            self._api_fetchers[source] = api_fetcher

    def _get_source_dir(self, source: str) -> Path:
        """Get the directory for a cache source."""
        return self.cache_dir / source

    def _get_snapshot_dir(self, source: str, version: int) -> Path:
        """Get the directory for a specific snapshot version."""
        return self._get_source_dir(source) / f"snapshot_v{version:04d}"

    def _get_current_link(self, source: str) -> Path:
        """Get the 'current' symlink path."""
        return self._get_source_dir(source) / "current"

    def _url_to_filename(self, url: str) -> str:
        """Convert URL to a safe filename."""
        # Use hash for uniqueness, keep some readable part
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        # Extract domain and path for readability
        from urllib.parse import urlparse
        parsed = urlparse(url)
        safe_path = parsed.path.replace("/", "_").strip("_")[:50]
        return f"{parsed.netloc}_{safe_path}_{url_hash}"

    def get_current_version(self, source: str) -> Optional[int]:
        """Get the current snapshot version for a source."""
        current_link = self._get_current_link(source)
        if not current_link.exists():
            return None

        try:
            target = current_link.resolve()
            # Extract version from directory name (snapshot_vXXXX)
            version_str = target.name.split("_v")[-1]
            return int(version_str)
        except (ValueError, OSError):
            return None

    def get_metadata(self, source: str, version: int = None) -> Optional[SnapshotMetadata]:
        """Get metadata for a snapshot."""
        if version is None:
            version = self.get_current_version(source)
        if version is None:
            return None

        # Check in-memory cache first
        cache_key = f"{source}_v{version}"
        if cache_key in self._metadata_cache:
            return self._metadata_cache[cache_key]

        # Read from file
        snapshot_dir = self._get_snapshot_dir(source, version)
        metadata_path = snapshot_dir / "metadata.json"

        if not metadata_path.exists():
            return None

        try:
            with open(metadata_path, "r") as f:
                data = json.load(f)
            metadata = SnapshotMetadata.from_dict(data)
            self._metadata_cache[cache_key] = metadata
            return metadata
        except (json.JSONDecodeError, KeyError, OSError) as e:
            logger.warning(f"Failed to read metadata for {source} v{version}: {e}")
            return None

    def is_cache_valid(self, source: str) -> bool:
        """Check if the current cache for a source is valid (not expired)."""
        metadata = self.get_metadata(source)
        if metadata is None:
            return False
        return not metadata.is_expired()

    async def ensure_fresh(
        self,
        source: str,
        force_refresh: bool = False,
    ) -> int:
        """
        Ensure cache is fresh, refreshing if needed.

        Args:
            source: Cache source name
            force_refresh: Force refresh even if cache is valid

        Returns:
            Current snapshot version number
        """
        with self.lock_manager.write_lock(source):
            if not force_refresh and self.is_cache_valid(source):
                return self.get_current_version(source)

            # Need to refresh
            return await self._refresh_cache_locked(source)

    async def _refresh_cache_locked(self, source: str) -> int:
        """
        Refresh cache for a source (must hold write lock).

        This is async to properly handle async fetchers.
        """
        logger.info(f"Refreshing cache for {source}...")

        # Determine new version number
        current_version = self.get_current_version(source)
        new_version = (current_version or 0) + 1

        # Create new snapshot directory
        snapshot_dir = self._get_snapshot_dir(source, new_version)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = snapshot_dir / "pages"
        pages_dir.mkdir(exist_ok=True)

        config = self.configs.get(source, CacheConfig())
        page_keys = []
        api_keys = []

        try:
            # Fetch and save API data
            if source in self._api_fetchers:
                api_data = await self._api_fetchers[source]()
                if api_data:
                    api_path = snapshot_dir / "api_data.json"
                    with open(api_path, "w") as f:
                        json.dump(api_data, f, indent=2)
                    api_keys = list(api_data.keys()) if isinstance(api_data, dict) else []

            # Fetch and save pages (if fetcher registered)
            if source in self._page_fetchers:
                pages = await self._page_fetchers[source]()
                if pages:
                    for url, content in pages.items():
                        filename = self._url_to_filename(url)
                        page_path = pages_dir / f"{filename}.html"
                        with open(page_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        page_keys.append(url)

            # Save metadata
            metadata = SnapshotMetadata(
                version=new_version,
                timestamp=time.time(),
                source=source,
                ttl=config.ttl,
                page_keys=page_keys,
                api_keys=api_keys,
            )
            metadata_path = snapshot_dir / "metadata.json"
            with open(metadata_path, "w") as f:
                json.dump(metadata.to_dict(), f, indent=2)

            # Update current symlink atomically
            current_link = self._get_current_link(source)
            temp_link = current_link.with_suffix(".tmp")

            # Remove old temp link if exists
            if temp_link.exists() or temp_link.is_symlink():
                temp_link.unlink()

            # Create new symlink and rename atomically
            temp_link.symlink_to(snapshot_dir.name)
            temp_link.rename(current_link)

            # Cleanup old versions
            self._cleanup_old_versions(source, config.max_versions)

            # Update in-memory cache
            cache_key = f"{source}_v{new_version}"
            self._metadata_cache[cache_key] = metadata

            logger.info(f"Cache refreshed for {source}: v{new_version}")
            return new_version

        except Exception as e:
            # Cleanup failed snapshot
            logger.error(f"Failed to refresh cache for {source}: {e}")
            if snapshot_dir.exists():
                shutil.rmtree(snapshot_dir, ignore_errors=True)
            raise

    def _cleanup_old_versions(self, source: str, max_versions: int):
        """Remove old snapshot versions beyond max_versions."""
        source_dir = self._get_source_dir(source)
        if not source_dir.exists():
            return

        # Find all snapshot directories
        snapshots = []
        for item in source_dir.iterdir():
            if item.is_dir() and item.name.startswith("snapshot_v"):
                try:
                    version = int(item.name.split("_v")[-1])
                    snapshots.append((version, item))
                except ValueError:
                    continue

        # Sort by version descending
        snapshots.sort(key=lambda x: x[0], reverse=True)

        # Remove old versions
        for version, path in snapshots[max_versions:]:
            logger.debug(f"Removing old cache version: {source} v{version}")
            shutil.rmtree(path, ignore_errors=True)
            # Also remove from in-memory cache
            cache_key = f"{source}_v{version}"
            self._metadata_cache.pop(cache_key, None)

    def get_page(
        self,
        source: str,
        url: str,
        version: int = None,
    ) -> Optional[str]:
        """
        Get cached page content.

        Args:
            source: Cache source name
            url: Page URL
            version: Specific version (default: current)

        Returns:
            Page HTML content or None if not found
        """
        if version is None:
            version = self.get_current_version(source)
        if version is None:
            return None

        with self.lock_manager.read_lock(source):
            snapshot_dir = self._get_snapshot_dir(source, version)
            filename = self._url_to_filename(url)
            page_path = snapshot_dir / "pages" / f"{filename}.html"

            if not page_path.exists():
                return None

            try:
                with open(page_path, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError as e:
                logger.warning(f"Failed to read cached page {url}: {e}")
                return None

    def get_api_data(
        self,
        source: str,
        key: str = None,
        version: int = None,
    ) -> Optional[Any]:
        """
        Get cached API data.

        Args:
            source: Cache source name
            key: Specific data key (default: return all data)
            version: Specific version (default: current)

        Returns:
            API data or None if not found
        """
        if version is None:
            version = self.get_current_version(source)
        if version is None:
            return None

        with self.lock_manager.read_lock(source):
            snapshot_dir = self._get_snapshot_dir(source, version)
            api_path = snapshot_dir / "api_data.json"

            if not api_path.exists():
                return None

            try:
                with open(api_path, "r") as f:
                    data = json.load(f)

                if key is None:
                    return data
                return data.get(key)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to read cached API data for {source}: {e}")
                return None

    def save_page(
        self,
        source: str,
        url: str,
        content: str,
        version: int = None,
    ):
        """
        Save a page to the current snapshot.

        Note: This should typically be done during refresh, not individually.
        """
        if version is None:
            version = self.get_current_version(source)
        if version is None:
            logger.warning(f"No current version for {source}, cannot save page")
            return

        with self.lock_manager.write_lock(source):
            snapshot_dir = self._get_snapshot_dir(source, version)
            pages_dir = snapshot_dir / "pages"
            pages_dir.mkdir(parents=True, exist_ok=True)

            filename = self._url_to_filename(url)
            page_path = pages_dir / f"{filename}.html"

            with open(page_path, "w", encoding="utf-8") as f:
                f.write(content)

    def save_api_data(
        self,
        source: str,
        data: Dict[str, Any],
        version: int = None,
    ):
        """
        Save API data to the current snapshot.

        Note: This should typically be done during refresh, not individually.
        """
        if version is None:
            version = self.get_current_version(source)
        if version is None:
            logger.warning(f"No current version for {source}, cannot save API data")
            return

        with self.lock_manager.write_lock(source):
            snapshot_dir = self._get_snapshot_dir(source, version)
            api_path = snapshot_dir / "api_data.json"

            # Merge with existing data if any
            existing = {}
            if api_path.exists():
                try:
                    with open(api_path, "r") as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass

            existing.update(data)

            with open(api_path, "w") as f:
                json.dump(existing, f, indent=2)

    def get_cache_info(self, source: str = None) -> Dict[str, Any]:
        """Get information about cache status."""
        if source:
            sources = [source]
        else:
            sources = list(self.configs.keys())

        info = {}
        for src in sources:
            metadata = self.get_metadata(src)
            if metadata:
                info[src] = {
                    "version": metadata.version,
                    "timestamp": metadata.timestamp,
                    "age_seconds": metadata.age_seconds(),
                    "expired": metadata.is_expired(),
                    "ttl": metadata.ttl,
                    "page_count": len(metadata.page_keys),
                    "api_keys": metadata.api_keys,
                }
            else:
                info[src] = {"status": "no_cache"}

        return info

    def clear_cache(self, source: str = None):
        """Clear cache for a source or all sources."""
        if source:
            sources = [source]
        else:
            sources = list(self.configs.keys())

        for src in sources:
            with self.lock_manager.write_lock(src):
                source_dir = self._get_source_dir(src)
                if source_dir.exists():
                    shutil.rmtree(source_dir)
                # Clear in-memory cache
                keys_to_remove = [k for k in self._metadata_cache if k.startswith(f"{src}_")]
                for key in keys_to_remove:
                    del self._metadata_cache[key]

        logger.info(f"Cleared cache for: {sources}")


class EvaluationCacheContext:
    """
    Context manager for evaluation that locks cache versions.

    Ensures that all cache reads during an evaluation use the same
    snapshot version, even if the cache is refreshed during evaluation.

    Usage:
        async with EvaluationCacheContext(cache_manager, ["coingecko", "stooq"]) as ctx:
            # All cache reads will use the versions locked at context entry
            page = ctx.get_page("coingecko", url)
            data = ctx.get_api_data("coingecko", key)
    """

    def __init__(
        self,
        cache_manager: CacheManager,
        sources: List[str],
        ensure_fresh: bool = True,
    ):
        self.cache_manager = cache_manager
        self.sources = sources
        self._ensure_fresh = ensure_fresh
        self.locked_versions: Dict[str, int] = {}

    async def __aenter__(self):
        """Lock cache versions for all required sources."""
        for source in self.sources:
            try:
                if self._ensure_fresh:
                    # Ensure cache is fresh and get version
                    version = await self.cache_manager.ensure_fresh(source)
                else:
                    version = self.cache_manager.get_current_version(source)

                if version is not None:
                    self.locked_versions[source] = version
                    logger.debug(f"Locked cache version: {source} v{version}")
            except Exception as e:
                logger.warning(f"Failed to initialize cache for {source}: {e}")
                # Continue without this source - will fall back to live API

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Release (nothing to do, versions are just recorded)."""
        pass

    def get_page(self, source: str, url: str) -> Optional[str]:
        """Get page using locked version."""
        version = self.locked_versions.get(source)
        return self.cache_manager.get_page(source, url, version)

    def get_api_data(self, source: str, key: str = None) -> Optional[Any]:
        """Get API data using locked version."""
        version = self.locked_versions.get(source)
        return self.cache_manager.get_api_data(source, key, version)

    def get_locked_version(self, source: str) -> Optional[int]:
        """Get the locked version for a source."""
        return self.locked_versions.get(source)


# Global cache manager instance
_global_cache_manager: Optional[CacheManager] = None


def get_cache_manager() -> CacheManager:
    """Get the global cache manager instance."""
    global _global_cache_manager
    if _global_cache_manager is None:
        _global_cache_manager = CacheManager()
    return _global_cache_manager


def set_cache_manager(manager: CacheManager):
    """Set the global cache manager instance."""
    global _global_cache_manager
    _global_cache_manager = manager
