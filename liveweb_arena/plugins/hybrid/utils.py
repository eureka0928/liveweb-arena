"""Shared utilities for hybrid plugin templates."""

import asyncio
import csv
import io
import logging
from typing import Any, Callable, Dict, Optional, TypeVar

import aiohttp

from liveweb_arena.plugins.coingecko.api_client import CoinGeckoClient

logger = logging.getLogger(__name__)

T = TypeVar('T')

# Stooq CSV download URL
STOOQ_CSV_URL = "https://stooq.com/q/d/l/"

# Thread-local cache context (set during evaluation)
_cache_context: Optional[Any] = None


def set_cache_context(context: Optional[Any]):
    """Set the cache context for current evaluation."""
    global _cache_context
    _cache_context = context


def get_cache_context() -> Optional[Any]:
    """Get the current cache context."""
    return _cache_context


async def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 10,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    operation_name: str = "operation",
) -> T:
    """
    Retry an async operation with exponential backoff.

    Args:
        func: Async function to retry
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay in seconds
        max_delay: Maximum delay cap in seconds
        operation_name: Name for logging purposes

    Returns:
        Result of the function

    Raises:
        RuntimeError: If all retries fail
    """
    last_exception = None

    for attempt in range(max_retries):
        try:
            result = await func()
            if result is not None:
                return result
            # If result is None, treat as retriable failure
            raise ValueError(f"{operation_name} returned None")
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at max_delay
                delay = min(base_delay * (2 ** attempt), max_delay)
                logger.warning(
                    f"{operation_name} failed (attempt {attempt + 1}/{max_retries}): {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"{operation_name} failed after {max_retries} attempts: {e}"
                )

    raise RuntimeError(
        f"{operation_name} failed after {max_retries} retries: {last_exception}"
    )


async def get_crypto_24h_change(coin_id: str) -> float:
    """
    Get 24h percentage change from CoinGecko with retry.

    Uses cache if available, otherwise falls back to live API.

    Args:
        coin_id: CoinGecko coin identifier

    Returns:
        24h percentage change

    Raises:
        RuntimeError: If all retries fail
    """
    # Try cache first
    ctx = get_cache_context()
    if ctx is not None:
        api_data = ctx.get_api_data("coingecko")
        if api_data:
            coins = api_data.get("coins", {})
            coin_data = coins.get(coin_id)
            if coin_data:
                change = coin_data.get("price_change_percentage_24h")
                if change is not None:
                    logger.debug(f"Cache hit: CoinGecko {coin_id} change={change}")
                    return change
            logger.debug(f"Cache miss for CoinGecko {coin_id}, falling back to API")

    # Fall back to live API with retry
    async def fetch():
        data = await CoinGeckoClient.get_coin_market_data(coin_id)
        if data and len(data) > 0:
            change = data[0].get("price_change_percentage_24h")
            if change is not None:
                return change
        return None

    return await retry_with_backoff(
        fetch,
        max_retries=10,
        base_delay=1.0,
        operation_name=f"CoinGecko fetch {coin_id}",
    )


async def get_stooq_price(symbol: str) -> float:
    """
    Get current price from Stooq with retry.

    Uses cache if available, otherwise falls back to live API.

    Args:
        symbol: Stooq symbol

    Returns:
        Current price

    Raises:
        RuntimeError: If all retries fail
    """
    # Try cache first
    ctx = get_cache_context()
    if ctx is not None:
        api_data = ctx.get_api_data("stooq")
        if api_data:
            assets = api_data.get("assets", {})
            asset_data = assets.get(symbol)
            if asset_data:
                price = asset_data.get("close")
                if price is not None:
                    logger.debug(f"Cache hit: Stooq {symbol} price={price}")
                    return price
            logger.debug(f"Cache miss for Stooq {symbol}, falling back to API")

    # Fall back to live API with retry
    async def fetch():
        async with aiohttp.ClientSession() as session:
            params = {"s": symbol, "i": "d"}
            async with session.get(
                STOOQ_CSV_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Stooq returned status {response.status}")
                csv_text = await response.text()

        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        if rows:
            close_val = rows[-1].get("Close")
            if close_val:
                return float(close_val)
        return None

    return await retry_with_backoff(
        fetch,
        max_retries=10,
        base_delay=1.0,
        operation_name=f"Stooq price {symbol}",
    )


async def get_stooq_24h_change(symbol: str) -> float:
    """
    Get daily percentage change from Stooq with retry.

    Uses cache if available, otherwise falls back to live API.

    Args:
        symbol: Stooq symbol

    Returns:
        Daily percentage change

    Raises:
        RuntimeError: If all retries fail
    """
    # Try cache first
    ctx = get_cache_context()
    if ctx is not None:
        api_data = ctx.get_api_data("stooq")
        if api_data:
            assets = api_data.get("assets", {})
            asset_data = assets.get(symbol)
            if asset_data:
                change = asset_data.get("daily_change_pct")
                if change is not None:
                    logger.debug(f"Cache hit: Stooq {symbol} change={change}")
                    return change
            logger.debug(f"Cache miss for Stooq {symbol}, falling back to API")

    # Fall back to live API with retry
    async def fetch():
        async with aiohttp.ClientSession() as session:
            params = {"s": symbol, "i": "d"}
            async with session.get(
                STOOQ_CSV_URL,
                params=params,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    raise RuntimeError(f"Stooq returned status {response.status}")
                csv_text = await response.text()

        reader = csv.DictReader(io.StringIO(csv_text))
        rows = list(reader)

        if len(rows) >= 2:
            current = float(rows[-1].get("Close", 0))
            previous = float(rows[-2].get("Close", 0))
            if previous > 0:
                return ((current - previous) / previous) * 100
        return None

    return await retry_with_backoff(
        fetch,
        max_retries=10,
        base_delay=1.0,
        operation_name=f"Stooq change {symbol}",
    )
