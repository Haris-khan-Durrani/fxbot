"""
src/strategy/trend.py
─────────────────────
EMA 50/200 trend detection on H1.
Returns BULLISH, BEARISH, or NEUTRAL.

EMA separation gate:
  When EMA50 and EMA200 are very close together (near a crossover), the
  trend call is noise. A minimum separation of `ema_min_separation_atr_ratio`
  × ATR(200) is required before reporting BULLISH or BEARISH.
  Below this threshold → NEUTRAL, which scores 0.5 (not 1.0 or 0.0).
"""
from __future__ import annotations

from enum import Enum

import pandas as pd

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _calc_atr_h1(df: pd.DataFrame, period: int) -> float:
    """ATR on H1 bars using EWM. Returns 0.0 if insufficient data."""
    if len(df) < period + 1:
        return 0.0
    recent = df.iloc[-(period * 3):]
    high = recent["high"]
    low = recent["low"]
    prev_close = recent["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else 0.0


def detect_trend(df_h1: pd.DataFrame) -> TrendDirection:
    """
    Evaluate EMA fast/slow crossover on H1 candles with a minimum separation gate.

    The EMA gap must exceed `ema_min_separation_atr_ratio × ATR(ema_slow)` to be
    considered a meaningful trend. Near-crossover states return NEUTRAL to prevent
    whipsaw entries scored at 100% trend confidence.

    Args:
        df_h1: H1 OHLCV DataFrame (must have 'close', 'high', 'low' columns, ≥200 rows).

    Returns:
        TrendDirection enum value.
    """
    fast = get("strategy.trend.ema_fast", 50)
    slow = get("strategy.trend.ema_slow", 200)
    min_sep_atr_ratio = get("strategy.trend.ema_min_separation_atr_ratio", 0.005)

    if len(df_h1) < slow:
        log.warning("Not enough H1 candles for EMA-%d (have %d). Returning NEUTRAL.", slow, len(df_h1))
        return TrendDirection.NEUTRAL

    close = df_h1["close"]
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)

    last_fast = float(ema_fast.iloc[-1])
    last_slow = float(ema_slow.iloc[-1])
    separation = abs(last_fast - last_slow)

    # Compute minimum required separation from ATR
    atr = _calc_atr_h1(df_h1, slow)
    min_separation = atr * min_sep_atr_ratio if atr > 0 else 0.0

    if separation < min_separation:
        log.debug(
            "Trend: EMA%d=%.5f EMA%d=%.5f gap=%.5f < min=%.5f (ATR=%.5f × %.4f) → NEUTRAL",
            fast, last_fast, slow, last_slow, separation, min_separation, atr, min_sep_atr_ratio,
        )
        return TrendDirection.NEUTRAL

    if last_fast > last_slow:
        direction = TrendDirection.BULLISH
    elif last_fast < last_slow:
        direction = TrendDirection.BEARISH
    else:
        direction = TrendDirection.NEUTRAL

    log.debug("Trend: EMA%d=%.5f  EMA%d=%.5f  gap=%.5f  → %s",
              fast, last_fast, slow, last_slow, separation, direction.value)
    return direction


def trend_score(direction: TrendDirection, signal_direction: str) -> float:
    """
    Return 0-1 score based on alignment between trend and proposed trade direction.
    1.0 = perfect alignment, 0.5 = neutral, 0.0 = counter-trend.
    """
    if direction == TrendDirection.NEUTRAL:
        return 0.5
    if direction == TrendDirection.BULLISH and signal_direction == "BUY":
        return 1.0
    if direction == TrendDirection.BEARISH and signal_direction == "SELL":
        return 1.0
    # Counter-trend trade
    return 0.0
