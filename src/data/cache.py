"""
src/data/cache.py
─────────────────
In-memory LRU cache for candle data with TTL-based invalidation.
Prevents hammering MT5 API on every loop tick.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from src.core.logger import get_logger

log = get_logger(__name__)


@dataclass
class _CacheEntry:
    data: pd.DataFrame
    fetched_at: float = field(default_factory=time.monotonic)


class CandleCache:
    """
    Thread-safe (GIL-level) candle cache.
    TTL is in seconds. Default: 10s for M15, 60s for H1.
    """

    _TIMEFRAME_TTL = {
        "M1": 5,
        "M5": 8,
        "M15": 10,
        "M30": 15,
        "H1": 60,
        "H4": 240,
        "D1": 600,
    }

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}

    def _key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}:{timeframe}"

    def get(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        key = self._key(symbol, timeframe)
        entry = self._store.get(key)
        if entry is None:
            return None
        ttl = self._TIMEFRAME_TTL.get(timeframe.upper(), 30)
        age = time.monotonic() - entry.fetched_at
        if age > ttl:
            log.debug("Cache MISS (expired) for %s — age=%.1fs ttl=%ds", key, age, ttl)
            del self._store[key]
            return None
        log.debug("Cache HIT for %s (age=%.1fs)", key, age)
        return entry.data.copy()

    def put(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        key = self._key(symbol, timeframe)
        self._store[key] = _CacheEntry(data=df.copy())
        log.debug("Cache SET for %s (%d rows)", key, len(df))

    def invalidate(self, symbol: Optional[str] = None, timeframe: Optional[str] = None) -> None:
        if symbol and timeframe:
            self._store.pop(self._key(symbol, timeframe), None)
        elif symbol:
            keys = [k for k in self._store if k.startswith(f"{symbol}:")]
            for k in keys:
                del self._store[k]
        else:
            self._store.clear()
            log.debug("Cache cleared entirely.")

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._store)}


# Global singleton cache
_cache = CandleCache()


def get_cached_candles(symbol: str, timeframe: str, fetcher, **kwargs) -> pd.DataFrame:
    """
    Get candles from cache, or call fetcher() if cache miss/expired.
    `fetcher` should be `candles.get_candles` or a backtest equivalent.
    """
    df = _cache.get(symbol, timeframe)
    if df is None:
        df = fetcher(symbol=symbol, timeframe=timeframe, **kwargs)
        _cache.put(symbol, timeframe, df)
    return df
