"""
Cache Adapters - Source-specific cache implementations.

Each adapter knows how to:
1. Fetch all relevant API data for a source
2. Fetch all relevant web pages for a source
3. Map between URLs and cache keys
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

from .cache_manager import CacheManager, get_cache_manager

logger = logging.getLogger(__name__)


class CoinGeckoCacheAdapter:
    """
    Cache adapter for CoinGecko.

    Caches:
    - Market data for top coins (prices, 24h change, market cap, etc.)
    - Coin detail pages
    """

    SOURCE = "coingecko"
    API_BASE = "https://api.coingecko.com/api/v3"

    # Top coins to cache (by market cap)
    CACHED_COINS = [
        "bitcoin", "ethereum", "tether", "binancecoin", "solana",
        "ripple", "usd-coin", "cardano", "dogecoin", "tron",
        "avalanche-2", "polkadot", "chainlink", "litecoin", "bitcoin-cash",
        "uniswap", "stellar", "cosmos", "near", "aptos",
        "sui", "bittensor", "internet-computer", "filecoin", "hedera",
    ]

    def __init__(self, cache_manager: CacheManager = None):
        self.cache = cache_manager or get_cache_manager()
        self._register_fetchers()

    def _register_fetchers(self):
        """Register API and page fetchers with cache manager."""
        self.cache.register_fetcher(
            self.SOURCE,
            api_fetcher=self._fetch_all_api_data,
            page_fetcher=None,  # Pages fetched on-demand
        )

    async def _fetch_all_api_data(self) -> Dict[str, Any]:
        """Fetch all coin market data from CoinGecko API."""
        logger.info("Fetching CoinGecko market data...")

        try:
            async with aiohttp.ClientSession() as session:
                # Fetch market data for all cached coins
                params = {
                    "vs_currency": "usd",
                    "ids": ",".join(self.CACHED_COINS),
                    "order": "market_cap_desc",
                    "per_page": 100,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d,30d",
                }

                async with session.get(
                    f"{self.API_BASE}/coins/markets",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        logger.error(f"CoinGecko API error: {response.status}")
                        return {}

                    data = await response.json()

            # Organize data by coin_id for easy lookup
            result = {
                "_meta": {
                    "source": "coingecko",
                    "endpoint": "coins/markets",
                    "coin_count": len(data),
                },
                "coins": {},
            }

            for coin in data:
                coin_id = coin.get("id")
                if coin_id:
                    result["coins"][coin_id] = coin

            logger.info(f"Cached {len(result['coins'])} coins from CoinGecko")
            return result

        except Exception as e:
            logger.error(f"Failed to fetch CoinGecko data: {e}")
            return {}

    def get_coin_data(self, coin_id: str, version: int = None) -> Optional[Dict]:
        """Get cached coin data."""
        api_data = self.cache.get_api_data(self.SOURCE, version=version)
        if not api_data:
            return None
        return api_data.get("coins", {}).get(coin_id)

    def get_all_coins_data(self, version: int = None) -> Dict[str, Dict]:
        """Get all cached coin data."""
        api_data = self.cache.get_api_data(self.SOURCE, version=version)
        if not api_data:
            return {}
        return api_data.get("coins", {})


class StooqCacheAdapter:
    """
    Cache adapter for Stooq.

    Caches:
    - Price data for stocks, indices, commodities
    """

    SOURCE = "stooq"
    CSV_URL = "https://stooq.com/q/d/l/"

    # Assets to cache
    CACHED_ASSETS = [
        # Indices
        "^spx", "^dji", "^ndx", "^dax", "^ukx", "^nkx",
        # Commodities
        "gc.f", "si.f", "cl.f", "ng.f", "hg.f",
        # US Stocks
        "aapl.us", "msft.us", "nvda.us", "tsla.us", "googl.us",
        "amzn.us", "meta.us", "jpm.us", "v.us", "wmt.us",
        "coin.us", "amd.us", "tlt.us",
    ]

    def __init__(self, cache_manager: CacheManager = None):
        self.cache = cache_manager or get_cache_manager()
        self._register_fetchers()

    def _register_fetchers(self):
        """Register API fetcher with cache manager."""
        self.cache.register_fetcher(
            self.SOURCE,
            api_fetcher=self._fetch_all_api_data,
            page_fetcher=None,
        )

    async def _fetch_all_api_data(self) -> Dict[str, Any]:
        """Fetch price data for all cached assets from Stooq."""
        logger.info("Fetching Stooq price data...")

        result = {
            "_meta": {
                "source": "stooq",
                "asset_count": 0,
            },
            "assets": {},
        }

        # Semaphore to limit concurrent requests
        semaphore = asyncio.Semaphore(5)

        async def fetch_one(session: aiohttp.ClientSession, symbol: str):
            """Fetch data for a single symbol."""
            async with semaphore:
                try:
                    params = {"s": symbol, "i": "d"}
                    async with session.get(
                        self.CSV_URL,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        if response.status != 200:
                            logger.warning(f"Stooq error for {symbol}: {response.status}")
                            return None

                        csv_text = await response.text()

                    # Parse CSV
                    lines = csv_text.strip().split("\n")
                    if len(lines) < 2:
                        return None

                    # Get headers and last row
                    headers = lines[0].split(",")
                    last_row = lines[-1].split(",")

                    if len(last_row) < len(headers):
                        return None

                    data = dict(zip(headers, last_row))

                    # Calculate daily change if we have previous day
                    current_close = float(data.get("Close", 0))
                    daily_change = None

                    if len(lines) >= 3:
                        prev_row = lines[-2].split(",")
                        if len(prev_row) >= len(headers):
                            prev_data = dict(zip(headers, prev_row))
                            prev_close = float(prev_data.get("Close", 0))
                            if prev_close > 0:
                                daily_change = ((current_close - prev_close) / prev_close) * 100

                    return {
                        "symbol": symbol,
                        "date": data.get("Date"),
                        "open": float(data.get("Open", 0)),
                        "high": float(data.get("High", 0)),
                        "low": float(data.get("Low", 0)),
                        "close": current_close,
                        "volume": float(data.get("Volume", 0)) if data.get("Volume") else None,
                        "daily_change_pct": daily_change,
                    }

                except asyncio.TimeoutError:
                    logger.warning(f"Stooq timeout for {symbol}")
                    return None
                except Exception as e:
                    logger.warning(f"Failed to fetch Stooq data for {symbol}: {e}")
                    return None

        async with aiohttp.ClientSession() as session:
            # Fetch all in parallel with concurrency limit
            tasks = [fetch_one(session, symbol) for symbol in self.CACHED_ASSETS]
            results = await asyncio.gather(*tasks)

            # Collect successful results
            for symbol, data in zip(self.CACHED_ASSETS, results):
                if data:
                    result["assets"][symbol] = data

        result["_meta"]["asset_count"] = len(result["assets"])
        logger.info(f"Cached {len(result['assets'])} assets from Stooq")
        return result

    def get_asset_data(self, symbol: str, version: int = None) -> Optional[Dict]:
        """Get cached asset data."""
        api_data = self.cache.get_api_data(self.SOURCE, version=version)
        if not api_data:
            return None
        return api_data.get("assets", {}).get(symbol)

    def get_all_assets_data(self, version: int = None) -> Dict[str, Dict]:
        """Get all cached asset data."""
        api_data = self.cache.get_api_data(self.SOURCE, version=version)
        if not api_data:
            return {}
        return api_data.get("assets", {})


class CacheAdapterRegistry:
    """Registry for all cache adapters."""

    def __init__(self, cache_manager: CacheManager = None):
        self.cache = cache_manager or get_cache_manager()
        self.adapters: Dict[str, Any] = {}

    def register(self, adapter):
        """Register an adapter."""
        self.adapters[adapter.SOURCE] = adapter

    def get(self, source: str):
        """Get adapter by source name."""
        return self.adapters.get(source)

    def initialize_all(self):
        """Initialize all default adapters."""
        self.register(CoinGeckoCacheAdapter(self.cache))
        self.register(StooqCacheAdapter(self.cache))
        return self

    async def refresh_all(self, sources: List[str] = None):
        """Refresh cache for specified sources or all."""
        if sources is None:
            sources = list(self.adapters.keys())

        for source in sources:
            try:
                await self.cache.ensure_fresh(source, force_refresh=True)
            except Exception as e:
                logger.error(f"Failed to refresh cache for {source}: {e}")


# Global adapter registry
_global_registry: Optional[CacheAdapterRegistry] = None


def get_adapter_registry() -> CacheAdapterRegistry:
    """Get the global adapter registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = CacheAdapterRegistry().initialize_all()
    return _global_registry
