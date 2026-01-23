"""Stooq API client with caching support"""

import asyncio
import csv
import io
import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Global cache context reference (set by env.py during evaluation)
_cache_context: Optional[Any] = None


def set_stooq_cache_context(context: Optional[Any]):
    """Set the cache context for Stooq API calls."""
    global _cache_context
    _cache_context = context


def get_stooq_cache_context() -> Optional[Any]:
    """Get the current cache context."""
    return _cache_context


class StooqClient:
    """
    Centralized Stooq API client with caching support.

    Uses CSV download endpoint for price data.
    """

    CSV_URL = "https://stooq.com/q/d/l/"

    # Rate limiting
    _last_request_time: float = 0
    _min_request_interval: float = 0.5  # seconds between requests
    _lock = asyncio.Lock()

    @classmethod
    async def _rate_limit(cls):
        """Apply rate limiting."""
        async with cls._lock:
            import time
            now = time.time()
            elapsed = now - cls._last_request_time
            if elapsed < cls._min_request_interval:
                await asyncio.sleep(cls._min_request_interval - elapsed)
            cls._last_request_time = time.time()

    @classmethod
    async def get_price_data(
        cls,
        symbol: str,
        timeout: float = 15.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Get price data for a symbol.

        Args:
            symbol: Stooq symbol (e.g., "gc.f", "^spx", "aapl.us")
            timeout: Request timeout in seconds

        Returns:
            Dict with price data or None on error:
            {
                "symbol": str,
                "date": str,
                "open": float,
                "high": float,
                "low": float,
                "close": float,
                "volume": float or None,
                "daily_change": float or None,
                "daily_change_pct": float or None,
            }
        """
        # Try cache first
        ctx = get_stooq_cache_context()
        if ctx is not None:
            api_data = ctx.get_api_data("stooq")
            if api_data:
                assets = api_data.get("assets", {})
                asset_data = assets.get(symbol)
                if asset_data:
                    logger.debug(f"Cache hit: Stooq {symbol}")
                    return asset_data
                logger.debug(f"Cache miss for Stooq {symbol}, falling back to API")

        # Fall back to live API
        await cls._rate_limit()

        try:
            async with aiohttp.ClientSession() as session:
                params = {"s": symbol, "i": "d"}
                async with session.get(
                    cls.CSV_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Stooq error for {symbol}: {response.status}")
                        return None
                    csv_text = await response.text()

            reader = csv.DictReader(io.StringIO(csv_text))
            rows = list(reader)

            if not rows:
                return None

            latest = rows[-1]

            def parse_float(val):
                try:
                    return float(val) if val else None
                except (ValueError, TypeError):
                    return None

            close = parse_float(latest.get("Close"))
            open_price = parse_float(latest.get("Open"))
            high = parse_float(latest.get("High"))
            low = parse_float(latest.get("Low"))
            volume = parse_float(latest.get("Volume"))

            # Calculate daily change if we have previous data
            daily_change = None
            daily_change_pct = None
            if len(rows) >= 2:
                prev = rows[-2]
                prev_close = parse_float(prev.get("Close"))
                if prev_close and close:
                    daily_change = close - prev_close
                    daily_change_pct = (daily_change / prev_close) * 100

            return {
                "symbol": symbol,
                "date": latest.get("Date"),
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "daily_change": daily_change,
                "daily_change_pct": daily_change_pct,
            }

        except asyncio.TimeoutError:
            logger.warning(f"Stooq timeout for {symbol}")
            return None
        except Exception as e:
            logger.warning(f"Stooq error for {symbol}: {e}")
            return None

    @classmethod
    async def get_historical_data(
        cls,
        symbol: str,
        timeout: float = 15.0,
    ) -> Optional[list]:
        """
        Get historical price data for a symbol.

        Args:
            symbol: Stooq symbol
            timeout: Request timeout in seconds

        Returns:
            List of daily price records or None on error
        """
        # Historical data is not cached (too large), always fetch live
        await cls._rate_limit()

        try:
            async with aiohttp.ClientSession() as session:
                params = {"s": symbol, "i": "d"}
                async with session.get(
                    cls.CSV_URL,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status != 200:
                        return None
                    csv_text = await response.text()

            reader = csv.DictReader(io.StringIO(csv_text))
            return list(reader)

        except Exception as e:
            logger.warning(f"Stooq historical error for {symbol}: {e}")
            return None
