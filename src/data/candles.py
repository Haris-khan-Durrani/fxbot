"""
src/data/candles.py
───────────────────
Fetch OHLCV candles from MT5 for M15 and H1 timeframes.
Validates data quality (no gaps, stale candles).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from src.core.logger import get_logger
from src.data.mt5_connection import MT5_AVAILABLE, ensure_connected

log = get_logger(__name__)

if MT5_AVAILABLE:
    import MetaTrader5 as mt5

# MT5 timeframe constants
TIMEFRAMES = {
    "M1":  1,
    "M5":  5,
    "M15": 15,
    "M30": 30,
    "H1":  16385,
    "H4":  16388,
    "D1":  16408,
}


def _mt5_tf(timeframe: str) -> int:
    if not MT5_AVAILABLE:
        return 0
    tf_map = {
        "M1":  mt5.TIMEFRAME_M1,
        "M5":  mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1":  mt5.TIMEFRAME_H1,
        "H4":  mt5.TIMEFRAME_H4,
        "D1":  mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(timeframe.upper())
    if tf is None:
        raise ValueError(f"Unknown timeframe: {timeframe}. Valid: {list(tf_map.keys())}")
    return tf


def get_candles(
    symbol: str,
    timeframe: str,
    count: int = 500,
    validate: bool = True,
) -> pd.DataFrame:
    """
    Fetch the last `count` closed candles for symbol/timeframe.
    Returns DataFrame with columns: time, open, high, low, close, tick_volume, spread.
    Raises RuntimeError if MT5 is not connected.
    """
    if not MT5_AVAILABLE:
        raise RuntimeError("MT5 package not available.")
    if not ensure_connected():
        raise RuntimeError("MT5 not connected — cannot fetch candles.")

    rates = mt5.copy_rates_from_pos(symbol, _mt5_tf(timeframe), 0, count)
    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        raise RuntimeError(f"Failed to fetch candles for {symbol} {timeframe}: {err}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df.set_index("time", inplace=True)
    df = df[["open", "high", "low", "close", "tick_volume", "spread"]]

    if validate:
        _validate_candles(df, symbol, timeframe)

    log.debug("Fetched %d %s %s candles (latest: %s)",
              len(df), symbol, timeframe, df.index[-1])
    return df


def _validate_candles(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """Check for stale data and excessive gaps. Logs warnings — does not raise."""
    if df.empty:
        log.warning("Candle validation: empty DataFrame for %s %s", symbol, timeframe)
        return

    # Check if last candle is too old
    tf_minutes = TIMEFRAMES.get(timeframe.upper(), 60)
    now_utc = datetime.now(timezone.utc)
    last_candle_time = df.index[-1].to_pydatetime()
    age_minutes = (now_utc - last_candle_time).total_seconds() / 60

    stale_threshold = tf_minutes * 3  # 3× the timeframe interval
    if age_minutes > stale_threshold:
        log.warning(
            "⚠️ Stale candles for %s %s: last candle is %.0f min old (threshold: %.0f min)",
            symbol, timeframe, age_minutes, stale_threshold,
        )

    # Check for internal gaps (only for minute-based timeframes)
    if tf_minutes <= 60 and len(df) > 2:
        time_diffs = df.index.to_series().diff().dropna()
        expected = pd.Timedelta(minutes=tf_minutes)
        # Allow up to 5× expected interval before flagging
        large_gaps = time_diffs[time_diffs > expected * 5]
        if len(large_gaps) > 0:
            log.warning(
                "⚠️ %d gap(s) detected in %s %s candles. Largest: %s",
                len(large_gaps), symbol, timeframe, large_gaps.max(),
            )
