"""Tests for cache module — CachedPage, normalize_url, url_to_cache_dir, CacheManager helpers."""

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from liveweb_arena.core.cache import (
    CachedPage,
    CacheFatalError,
    CacheManager,
    PageRequirement,
    normalize_url,
    safe_path_component,
    url_to_cache_dir,
)


# ── CachedPage ──────────────────────────────────────────────────────


class TestCachedPage:
    def test_is_complete_with_api(self):
        page = CachedPage(url="u", html="h", api_data={"k": "v"}, fetched_at=1.0, need_api=True)
        assert page.is_complete()

    def test_is_incomplete_missing_api(self):
        page = CachedPage(url="u", html="h", api_data=None, fetched_at=1.0, need_api=True)
        assert not page.is_complete()

    def test_is_incomplete_empty_api(self):
        page = CachedPage(url="u", html="h", api_data={}, fetched_at=1.0, need_api=True)
        assert not page.is_complete()

    def test_is_complete_no_api_needed(self):
        page = CachedPage(url="u", html="h", api_data=None, fetched_at=1.0, need_api=False)
        assert page.is_complete()

    def test_is_expired(self):
        page = CachedPage(url="u", html="h", api_data=None, fetched_at=time.time() - 100, need_api=False)
        assert page.is_expired(ttl=50)
        assert not page.is_expired(ttl=200)

    def test_roundtrip_to_dict_from_dict(self):
        page = CachedPage(
            url="https://example.com",
            html="<h1>hi</h1>",
            api_data={"price": 42},
            fetched_at=1234567890.0,
            accessibility_tree="heading: hi",
            need_api=True,
        )
        d = page.to_dict()
        restored = CachedPage.from_dict(d)
        assert restored.url == page.url
        assert restored.html == page.html
        assert restored.api_data == page.api_data
        assert restored.fetched_at == page.fetched_at
        assert restored.accessibility_tree == page.accessibility_tree
        assert restored.need_api == page.need_api

    def test_from_dict_defaults(self):
        """Old cache format without need_api defaults to True."""
        d = {"url": "u", "html": "h", "api_data": None, "fetched_at": 1.0}
        page = CachedPage.from_dict(d)
        assert page.need_api is True
        assert page.accessibility_tree is None

    def test_to_dict_omits_none_a11y(self):
        page = CachedPage(url="u", html="h", api_data=None, fetched_at=1.0)
        d = page.to_dict()
        assert "accessibility_tree" not in d

    def test_to_dict_includes_a11y(self):
        page = CachedPage(url="u", html="h", api_data=None, fetched_at=1.0, accessibility_tree="tree")
        d = page.to_dict()
        assert d["accessibility_tree"] == "tree"


# ── PageRequirement ──────────────────────────────────────────────────


class TestPageRequirement:
    def test_nav(self):
        req = PageRequirement.nav("https://example.com")
        assert req.url == "https://example.com"
        assert req.need_api is False

    def test_data(self):
        req = PageRequirement.data("https://example.com")
        assert req.need_api is True


# ── normalize_url ────────────────────────────────────────────────────


class TestNormalizeUrl:
    def test_lowercase_domain(self):
        assert "example.com" in normalize_url("https://EXAMPLE.COM/Path")

    def test_preserves_path(self):
        result = normalize_url("https://example.com/en/coins/bitcoin")
        assert "/en/coins/bitcoin" in result

    def test_removes_default_port_80(self):
        result = normalize_url("http://example.com:80/page")
        assert ":80" not in result
        assert "example.com/page" in result

    def test_removes_default_port_443(self):
        result = normalize_url("https://example.com:443/page")
        assert ":443" not in result

    def test_keeps_non_default_port(self):
        result = normalize_url("http://localhost:8080/api")
        assert ":8080" in result

    def test_strips_tracking_params(self):
        result = normalize_url("https://example.com/page?utm_source=google&id=123")
        assert "utm_source" not in result
        assert "id=123" in result

    def test_sorts_query_params(self):
        result = normalize_url("https://example.com/page?z=1&a=2")
        assert result.endswith("?a=2&z=1")

    def test_decodes_percent_encoding(self):
        result = normalize_url("https://example.com/caf%C3%A9")
        assert "café" in result

    def test_empty_path_gets_slash(self):
        result = normalize_url("https://example.com")
        assert result.endswith("example.com/")

    def test_idempotent(self):
        url = "https://www.coingecko.com/en/coins/bitcoin?utm_source=x"
        assert normalize_url(url) == normalize_url(normalize_url(url))


# ── safe_path_component ──────────────────────────────────────────────


class TestSafePathComponent:
    def test_replaces_dangerous_chars(self):
        result = safe_path_component('file<name>:with"bad|chars')
        assert "<" not in result
        assert ">" not in result
        assert ":" not in result
        assert '"' not in result
        assert "|" not in result

    def test_replaces_spaces(self):
        assert "_" in safe_path_component("hello world")

    def test_truncates_long_strings(self):
        result = safe_path_component("a" * 300)
        assert len(result) == 200


# ── url_to_cache_dir ─────────────────────────────────────────────────


class TestUrlToCacheDir:
    def test_basic_path(self):
        result = url_to_cache_dir(Path("/cache"), "https://www.coingecko.com/en/coins/bitcoin")
        assert result == Path("/cache/www.coingecko.com/en/coins/bitcoin")

    def test_query_params(self):
        result = url_to_cache_dir(Path("/cache"), "https://stooq.com/q/?s=aapl.us")
        parts = str(result)
        assert "stooq.com" in parts
        assert "aapl.us" in parts

    def test_root_path(self):
        result = url_to_cache_dir(Path("/cache"), "https://example.com")
        assert "_root_" in str(result)

    def test_strips_default_port(self):
        result = url_to_cache_dir(Path("/cache"), "https://example.com:443/page")
        assert ":443" not in str(result)


# ── CacheFatalError ──────────────────────────────────────────────────


class TestCacheFatalError:
    def test_basic(self):
        err = CacheFatalError("timeout", url="https://x.com")
        assert str(err) == "timeout"
        assert err.url == "https://x.com"

    def test_no_url(self):
        err = CacheFatalError("generic failure")
        assert err.url is None


# ── CacheManager._load_if_valid (via file I/O) ──────────────────────


class TestCacheManagerLoadIfValid:
    def test_returns_none_for_missing_file(self, tmp_path):
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(tmp_path / "nonexistent.json", need_api=False) is None

    def test_loads_valid_cache(self, tmp_path):
        cache_file = tmp_path / "page.json"
        page = CachedPage(url="https://x.com", html="<h1>x</h1>", api_data={"k": 1}, fetched_at=time.time(), need_api=True)
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        loaded = mgr._load_if_valid(cache_file, need_api=True)
        assert loaded is not None
        assert loaded.url == "https://x.com"

    def test_rejects_expired_cache(self, tmp_path):
        cache_file = tmp_path / "page.json"
        page = CachedPage(url="https://x.com", html="h", api_data={"k": 1}, fetched_at=1.0, need_api=True)
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(cache_file, need_api=True) is None
        assert not cache_file.exists()  # expired cache deleted

    def test_rejects_incomplete_cache(self, tmp_path):
        cache_file = tmp_path / "page.json"
        page = CachedPage(url="https://x.com", html="h", api_data=None, fetched_at=time.time(), need_api=True)
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(cache_file, need_api=True) is None

    def test_rejects_corrupted_cache(self, tmp_path):
        cache_file = tmp_path / "page.json"
        cache_file.write_text("not json at all")
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(cache_file, need_api=False) is None
        assert not cache_file.exists()  # corrupted cache deleted

    def test_upgrade_nav_to_data_rejects(self, tmp_path):
        """Cache was saved as nav (no API) but now we need data (need_api=True)."""
        cache_file = tmp_path / "page.json"
        page = CachedPage(url="https://x.com", html="h", api_data=None, fetched_at=time.time(), need_api=False)
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        # need_api=True but cache has no api_data → rejected
        assert mgr._load_if_valid(cache_file, need_api=True) is None

    def test_rejects_captcha_cache(self, tmp_path):
        """CAPTCHA HTML must be rejected and deleted on load."""
        cache_file = tmp_path / "page.json"
        page = CachedPage(
            url="https://taostats.io/subnets/1",
            html='<html><head><title>Just a moment...</title></head><body>challenge</body></html>',
            api_data=None, fetched_at=time.time(), need_api=False,
        )
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(cache_file, need_api=False) is None
        assert not cache_file.exists()

    def test_rejects_short_html_no_api(self, tmp_path):
        """Trivially short HTML without api_data is garbage — reject and delete."""
        cache_file = tmp_path / "page.json"
        page = CachedPage(
            url="https://stooq.com/q?s=bad",
            html='<html><head></head><body></body></html>',
            api_data=None, fetched_at=time.time(), need_api=False,
        )
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_if_valid(cache_file, need_api=False) is None
        assert not cache_file.exists()

    def test_keeps_short_html_with_api(self, tmp_path):
        """Short HTML is fine when api_data provides the real value (e.g. API endpoints)."""
        cache_file = tmp_path / "page.json"
        page = CachedPage(
            url="https://api.taostats.io/subnets",
            html='<html><head></head><body></body></html>',
            api_data={"subnets": [1, 2]}, fetched_at=time.time(), need_api=True,
        )
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        loaded = mgr._load_if_valid(cache_file, need_api=True)
        assert loaded is not None
        assert loaded.api_data == {"subnets": [1, 2]}

    def test_stale_fallback_rejects_captcha(self, tmp_path):
        """Stale fallback must also reject CAPTCHA — never serve challenge pages."""
        cache_file = tmp_path / "page.json"
        page = CachedPage(
            url="https://taostats.io/subnets/1",
            html='<html><head><title>Just a moment...</title></head><body></body></html>',
            api_data=None, fetched_at=1.0, need_api=False,  # expired
        )
        with open(cache_file, "w") as f:
            json.dump(page.to_dict(), f)
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        assert mgr._load_stale(cache_file, need_api=False) is None
        assert not cache_file.exists()


# ── _fetch_page_with_retry ──────────────────────────────────────────


class TestFetchPageWithRetry:
    """Tests for CacheManager._fetch_page_with_retry."""

    def _make_manager(self, tmp_path):
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        mgr._PAGE_RETRY_DELAY = 0  # no waiting in tests
        return mgr

    def test_succeeds_on_first_attempt(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(return_value=("<html>ok</html>", "tree"))
        html, tree = asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert html == "<html>ok</html>"
        assert mgr._fetch_page.call_count == 1

    def test_retries_on_transient_error(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(side_effect=[
            TimeoutError("page.goto timed out"),
            ("<html>ok</html>", "tree"),
        ])
        html, tree = asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert html == "<html>ok</html>"
        assert mgr._fetch_page.call_count == 2

    def test_retries_on_http_5xx(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(side_effect=[
            CacheFatalError("HTTP 503 for https://arxiv.org/list/cs.AI/new"),
            ("<html>ok</html>", "tree"),
        ])
        html, _ = asyncio.run(mgr._fetch_page_with_retry("https://arxiv.org/list/cs.AI/new"))
        assert html == "<html>ok</html>"
        assert mgr._fetch_page.call_count == 2

    def test_retries_on_http_429(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(side_effect=[
            CacheFatalError("HTTP 429 for https://arxiv.org/list/cs.AI/new"),
            ("<html>ok</html>", "tree"),
        ])
        html, _ = asyncio.run(mgr._fetch_page_with_retry("https://arxiv.org/list/cs.AI/new"))
        assert html == "<html>ok</html>"
        assert mgr._fetch_page.call_count == 2

    def test_does_not_retry_http_404(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(
            side_effect=CacheFatalError("HTTP 404 for https://x.com"),
        )
        with pytest.raises(CacheFatalError, match="HTTP 404"):
            asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert mgr._fetch_page.call_count == 1

    def test_does_not_retry_http_403(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(
            side_effect=CacheFatalError("HTTP 403 for https://x.com"),
        )
        with pytest.raises(CacheFatalError, match="HTTP 403"):
            asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert mgr._fetch_page.call_count == 1

    def test_does_not_retry_captcha(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(
            side_effect=CacheFatalError("CAPTCHA/challenge page detected"),
        )
        with pytest.raises(CacheFatalError, match="CAPTCHA"):
            asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert mgr._fetch_page.call_count == 1

    def test_raises_after_all_retries_exhausted(self, tmp_path):
        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(
            side_effect=TimeoutError("page.goto timed out"),
        )
        with pytest.raises(CacheFatalError, match="Page fetch failed"):
            asyncio.run(mgr._fetch_page_with_retry("https://x.com"))
        assert mgr._fetch_page.call_count == mgr._MAX_PAGE_RETRIES


# ── _ensure_single fetch strategy ───────────────────────────────────


class TestEnsureSingleFetchStrategy:
    """Tests that _ensure_single picks sequential vs concurrent fetch correctly."""

    def _make_manager(self, tmp_path):
        mgr = CacheManager(cache_dir=tmp_path, ttl=3600)
        mgr._PAGE_RETRY_DELAY = 0
        return mgr

    def test_sequential_when_plugin_overrides_extract(self, tmp_path):
        """Plugins that override extract_api_data_from_html get sequential
        fetch — no concurrent API call."""
        from liveweb_arena.plugins.base import BasePlugin

        class _HtmlExtractPlugin(BasePlugin):
            name = "test_extract"
            allowed_domains = ["example.com"]

            def extract_api_data_from_html(self, url, html):
                return {"extracted": True}

            async def fetch_api_data(self, url):
                raise AssertionError("should not be called")

        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(return_value=("<html>data</html>", "tree"))
        plugin = _HtmlExtractPlugin()

        cached = asyncio.run(mgr._ensure_single(
            "https://example.com/page", plugin, need_api=True,
        ))
        assert cached.api_data == {"extracted": True}

    def test_falls_back_to_fetch_api_data_when_extract_returns_none(self, tmp_path):
        """When extract_api_data_from_html is overridden but returns None for
        a particular URL, fall back to fetch_api_data (honour the contract)."""
        from liveweb_arena.plugins.base import BasePlugin

        class _PartialExtractPlugin(BasePlugin):
            name = "test_partial"
            allowed_domains = ["example.com"]

            def extract_api_data_from_html(self, url, html):
                # Returns None for this URL — can't extract from HTML
                return None

            async def fetch_api_data(self, url):
                return {"fallback": "api_data"}

        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(return_value=("<html>page</html>", "tree"))
        plugin = _PartialExtractPlugin()

        cached = asyncio.run(mgr._ensure_single(
            "https://example.com/page", plugin, need_api=True,
        ))
        assert cached.api_data == {"fallback": "api_data"}

    def test_fallback_fetch_api_data_error_wrapped_as_cache_fatal(self, tmp_path):
        """When extract returns None and fetch_api_data raises, the error must
        be wrapped as CacheFatalError so the stale-cache fallback path runs."""
        from liveweb_arena.plugins.base import BasePlugin
        from liveweb_arena.plugins.base_client import APIFetchError

        class _FailFallbackPlugin(BasePlugin):
            name = "test_fail_fallback"
            allowed_domains = ["example.com"]

            def extract_api_data_from_html(self, url, html):
                return None  # triggers fallback

            async def fetch_api_data(self, url):
                raise APIFetchError("service down", source="test")

        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(return_value=("<html>page</html>", "tree"))
        plugin = _FailFallbackPlugin()

        with pytest.raises(CacheFatalError, match="API data fetch failed"):
            asyncio.run(mgr._ensure_single(
                "https://example.com/page", plugin, need_api=True,
            ))

    def test_concurrent_when_plugin_does_not_override_extract(self, tmp_path):
        """Plugins without extract_api_data_from_html get concurrent
        page + API fetch (no performance regression)."""
        from liveweb_arena.plugins.base import BasePlugin

        class _ConcurrentPlugin(BasePlugin):
            name = "test_concurrent"
            allowed_domains = ["example.com"]

            async def fetch_api_data(self, url):
                return {"api": "data"}

        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(return_value=("<html>page</html>", "tree"))
        plugin = _ConcurrentPlugin()

        cached = asyncio.run(mgr._ensure_single(
            "https://example.com/page", plugin, need_api=True,
        ))
        assert cached.api_data == {"api": "data"}

    def test_concurrent_cancels_api_on_page_failure(self, tmp_path):
        """When page fetch fails in concurrent mode, API task is cancelled."""
        from liveweb_arena.plugins.base import BasePlugin

        api_called = False

        class _FailPlugin(BasePlugin):
            name = "test_fail"
            allowed_domains = ["example.com"]

            async def fetch_api_data(self, url):
                nonlocal api_called
                await asyncio.sleep(10)  # would hang if not cancelled
                api_called = True
                return {"api": "data"}

        mgr = self._make_manager(tmp_path)
        mgr._fetch_page = AsyncMock(
            side_effect=CacheFatalError("HTTP 500 for https://example.com/page"),
        )
        plugin = _FailPlugin()

        with pytest.raises(CacheFatalError, match="Page fetch failed"):
            asyncio.run(mgr._ensure_single(
                "https://example.com/page", plugin, need_api=True,
            ))
        assert not api_called
