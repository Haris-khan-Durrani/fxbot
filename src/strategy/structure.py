"""
src/strategy/structure.py
─────────────────────────
Break of Structure (BOS) detection on M15.
Identifies swing highs/lows and detects whether price has broken beyond them.

ATR-normalised minimum break distance filter:
  A BOS is only confirmed when the break distance (close − swing_high) is at
  least `bos_min_break_atr_ratio × ATR(14)`.  This filters out sub-spread
  noise breaks that appear as real BOS on floating-point data but are
  indistinguishable from bid/ask jitter (critical for XAUUSD at $4 300+).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)


class BOSDirection(str, Enum):
    BULLISH = "BULLISH"   # BOS to the upside (breakout above swing high)
    BEARISH = "BEARISH"   # BOS to the downside (break below swing low)
    NONE = "NONE"


@dataclass
class BOSResult:
    direction: BOSDirection
    break_level: Optional[float]    # Price level that was broken
    confidence: float               # 0.0 to 1.0


def _find_swing_high(df: pd.DataFrame, lookback: int, confirm: int) -> Optional[float]:
    """Find the highest 'high' in the lookback period prior to confirmation bars."""
    window = df["high"].iloc[-(lookback + confirm):-confirm]
    if window.empty:
        return None
    return float(window.max())


def _find_swing_low(df: pd.DataFrame, lookback: int, confirm: int) -> Optional[float]:
    """Find the lowest 'low' in the lookback period prior to confirmation bars."""
    window = df["low"].iloc[-(lookback + confirm):-confirm]
    if window.empty:
        return None
    return float(window.min())


def _calc_atr(df: pd.DataFrame, period: int) -> float:
    """
    Calculate ATR(period) on the last `period * 3` bars.
    Uses standard True Range: max(H-L, |H-prev_C|, |L-prev_C|).
    Returns 0.0 if not enough data.
    """
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


def detect_bos(df_m15: pd.DataFrame) -> BOSResult:
    """
    Detect Break of Structure on M15 timeframe.

    A bullish BOS occurs when the close of `confirmation_bars` consecutive candles
    is above the recent swing high AND the break distance ≥ ATR × min_break_ratio.
    A bearish BOS occurs when they close below the recent swing low by the same gate.

    Args:
        df_m15: M15 OHLCV DataFrame (needs at least lookback + confirmation_bars rows).

    Returns:
        BOSResult with direction, level, and confidence.
    """
    lookback = get("strategy.structure.bos_lookback_bars", 20)
    confirm = get("strategy.structure.bos_confirmation_bars", 2)
    min_break_atr_ratio = get("strategy.structure.bos_min_break_atr_ratio", 0.10)
    atr_period = get("risk.atr_period", 14)

    min_required = lookback + confirm + 5
    if len(df_m15) < min_required:
        log.warning("BOS: not enough M15 bars (have %d, need %d)", len(df_m15), min_required)
        return BOSResult(direction=BOSDirection.NONE, break_level=None, confidence=0.0)

    swing_high = _find_swing_high(df_m15, lookback, confirm)
    swing_low = _find_swing_low(df_m15, lookback, confirm)

    if swing_high is None or swing_low is None:
        return BOSResult(direction=BOSDirection.NONE, break_level=None, confidence=0.0)

    # Compute ATR-based minimum break distance
    atr = _calc_atr(df_m15, atr_period)
    min_break_distance = atr * min_break_atr_ratio if atr > 0 else 0.0

    # Check last `confirm` candles for a confirmed break
    recent_closes = df_m15["close"].iloc[-confirm:]

    bullish_break = all(recent_closes > swing_high)
    bearish_break = all(recent_closes < swing_low)

    if bullish_break:
        break_distance = float(recent_closes.iloc[-1] - swing_high)

        # ATR gate: reject sub-noise breaks
        if break_distance < min_break_distance:
            log.debug(
                "BOS BULLISH rejected: break_distance=%.5f < min=%.5f (ATR=%.5f × %.2f)",
                break_distance, min_break_distance, atr, min_break_atr_ratio,
            )
            return BOSResult(direction=BOSDirection.NONE, break_level=None, confidence=0.0)

        candle_range = float(df_m15["high"].iloc[-1] - df_m15["low"].iloc[-1])
        confidence = min(1.0, break_distance / max(candle_range, 1e-8))
        log.debug("BOS BULLISH: above %.5f  break=%.5f  conf=%.2f",
                  swing_high, break_distance, confidence)
        return BOSResult(
            direction=BOSDirection.BULLISH,
            break_level=swing_high,
            confidence=max(0.5, confidence),
        )

    if bearish_break:
        break_distance = float(swing_low - recent_closes.iloc[-1])

        # ATR gate: reject sub-noise breaks
        if break_distance < min_break_distance:
            log.debug(
                "BOS BEARISH rejected: break_distance=%.5f < min=%.5f (ATR=%.5f × %.2f)",
                break_distance, min_break_distance, atr, min_break_atr_ratio,
            )
            return BOSResult(direction=BOSDirection.NONE, break_level=None, confidence=0.0)

        candle_range = float(df_m15["high"].iloc[-1] - df_m15["low"].iloc[-1])
        confidence = min(1.0, break_distance / max(candle_range, 1e-8))
        log.debug("BOS BEARISH: below %.5f  break=%.5f  conf=%.2f",
                  swing_low, break_distance, confidence)
        return BOSResult(
            direction=BOSDirection.BEARISH,
            break_level=swing_low,
            confidence=max(0.5, confidence),
        )

    return BOSResult(direction=BOSDirection.NONE, break_level=None, confidence=0.0)


def bos_score(result: BOSResult, signal_direction: str) -> float:
    """Return 0-1 score for BOS alignment with signal direction."""
    if result.direction == BOSDirection.NONE:
        return 0.0
    if (result.direction == BOSDirection.BULLISH and signal_direction == "BUY") or \
       (result.direction == BOSDirection.BEARISH and signal_direction == "SELL"):
        return result.confidence
    return 0.0
