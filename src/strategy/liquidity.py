"""
src/strategy/liquidity.py
─────────────────────────
Liquidity sweep detection on M15.
A sweep occurs when price wicks beyond a recent swing high/low and then reverses.
This indicates stop-hunting by smart money before a move.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)


@dataclass
class SweepResult:
    detected: bool
    direction: str          # "BULLISH" (swept lows → expect up) | "BEARISH" (swept highs → expect down)
    sweep_level: Optional[float]
    confidence: float       # 0.0 to 1.0


def detect_liquidity_sweep(df_m15: pd.DataFrame) -> SweepResult:
    """
    Detect a liquidity sweep on M15.

    A bullish setup (expect price to go UP):
      - Price wicks below a recent swing low (sweeps sell-side liquidity)
      - Then the candle closes ABOVE the swing low (wick rejection)
      - Wick size ≥ sweep_wick_ratio of the total candle range

    A bearish setup (expect price to go DOWN):
      - Price wicks above a recent swing high (sweeps buy-side liquidity)
      - Then the candle closes BELOW the swing high (wick rejection)

    Args:
        df_m15: M15 OHLCV DataFrame.

    Returns:
        SweepResult
    """
    lookback = get("strategy.liquidity.sweep_lookback_bars", 15)
    wick_ratio_min = get("strategy.liquidity.sweep_wick_ratio", 0.5)

    if len(df_m15) < lookback + 3:
        return SweepResult(detected=False, direction="NONE", sweep_level=None, confidence=0.0)

    # Find swing high/low in the lookback window (excluding last 2 bars)
    lookback_df = df_m15.iloc[-(lookback + 2):-2]
    swing_high = float(lookback_df["high"].max())
    swing_low = float(lookback_df["low"].min())

    # Analyse the last completed candle
    last = df_m15.iloc[-1]
    prev = df_m15.iloc[-2]

    candle_high = last["high"]
    candle_low = last["low"]
    candle_open = last["open"]
    candle_close = last["close"]
    candle_range = candle_high - candle_low

    if candle_range < 1e-8:
        return SweepResult(detected=False, direction="NONE", sweep_level=None, confidence=0.0)

    # ── Bullish sweep (sweeps below swing low, closes back above) ──
    if candle_low < swing_low and candle_close > swing_low:
        lower_wick = swing_low - candle_low   # How far it swept below
        upper_body = candle_close - candle_open if candle_close > candle_open else 0
        wick_pct = lower_wick / candle_range
        if wick_pct >= wick_ratio_min:
            confidence = min(1.0, wick_pct)
            log.debug("Liquidity SWEEP (bullish): swept %.5f  wick_pct=%.2f  conf=%.2f",
                      swing_low, wick_pct, confidence)
            return SweepResult(
                detected=True, direction="BULLISH",
                sweep_level=swing_low, confidence=confidence,
            )

    # ── Bearish sweep (sweeps above swing high, closes back below) ─
    if candle_high > swing_high and candle_close < swing_high:
        upper_wick = candle_high - swing_high
        wick_pct = upper_wick / candle_range
        if wick_pct >= wick_ratio_min:
            confidence = min(1.0, wick_pct)
            log.debug("Liquidity SWEEP (bearish): swept %.5f  wick_pct=%.2f  conf=%.2f",
                      swing_high, wick_pct, confidence)
            return SweepResult(
                detected=True, direction="BEARISH",
                sweep_level=swing_high, confidence=confidence,
            )

    return SweepResult(detected=False, direction="NONE", sweep_level=None, confidence=0.0)


def liquidity_score(result: SweepResult, signal_direction: str) -> float:
    """Return 0-1 score for sweep alignment with signal direction."""
    if not result.detected:
        return 0.0
    if (result.direction == "BULLISH" and signal_direction == "BUY") or \
       (result.direction == "BEARISH" and signal_direction == "SELL"):
        return result.confidence
    return 0.0
