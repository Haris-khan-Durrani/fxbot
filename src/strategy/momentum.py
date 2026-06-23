"""
src/strategy/momentum.py
────────────────────────
RSI-based momentum analysis on M15.
Scoring is direction-aware: the same RSI level means different things for
a BUY setup vs a SELL setup.

Scoring table (0-1 scale):
  BUY setup:
    RSI ≤ oversold   (≤30) → 1.0  (ideal oversold bounce)
    RSI 30–50        → 0.5  (recovering, still below mid)
    RSI 50–overbought(50-70) → 0.8  (healthy bullish continuation)
    RSI > overbought (>70)  → 0.3  (extended, but not disqualified)

  SELL setup (mirror):
    RSI ≥ overbought (≥70) → 1.0
    RSI 50–70        → 0.5
    RSI 30–50        → 0.8  (healthy bearish continuation)
    RSI < oversold   (<30)  → 0.3
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)


class MomentumState(str, Enum):
    OVERSOLD = "OVERSOLD"            # RSI < oversold level → bullish context
    BULLISH_NEUTRAL = "BULLISH_NEUTRAL"  # RSI in upper neutral zone (50–70)
    BEARISH_NEUTRAL = "BEARISH_NEUTRAL"  # RSI in lower neutral zone (30–50)
    OVERBOUGHT = "OVERBOUGHT"        # RSI > overbought level → bearish context


@dataclass
class MomentumResult:
    rsi_value: float
    state: MomentumState


def calc_rsi(close: pd.Series, period: int) -> pd.Series:
    """Compute RSI using Wilder's smoothing (EWM)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    # When avg_loss == 0 (pure uptrend), RS = infinity → RSI = 100
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - (100 / (1 + rs))).fillna(100)


def detect_momentum(df_m15: pd.DataFrame) -> MomentumResult:
    """
    Calculate RSI on M15 and classify momentum state.

    Args:
        df_m15: M15 OHLCV DataFrame.

    Returns:
        MomentumResult with rsi_value and state.
    """
    period = get("strategy.momentum.rsi_period", 14)
    oversold = get("strategy.momentum.rsi_oversold", 30)
    overbought = get("strategy.momentum.rsi_overbought", 70)
    rsi_mid = get("strategy.momentum.rsi_mid", 50)

    min_rows = period * 2
    if len(df_m15) < min_rows:
        log.warning("RSI: not enough M15 bars (have %d, need %d)", len(df_m15), min_rows)
        return MomentumResult(rsi_value=50.0, state=MomentumState.BULLISH_NEUTRAL)

    rsi_series = calc_rsi(df_m15["close"], period)
    rsi = float(rsi_series.iloc[-1])

    if rsi <= oversold:
        state = MomentumState.OVERSOLD
    elif rsi >= overbought:
        state = MomentumState.OVERBOUGHT
    elif rsi >= rsi_mid:
        state = MomentumState.BULLISH_NEUTRAL   # 50–70 zone
    else:
        state = MomentumState.BEARISH_NEUTRAL   # 30–50 zone

    log.debug("Momentum: RSI(%.0f)=%.2f  state=%s", period, rsi, state.value)
    return MomentumResult(rsi_value=rsi, state=state)


def momentum_score(result: MomentumResult, signal_direction: str) -> float:
    """
    Return 0–1 score for momentum alignment with signal direction.

    Direction-aware scoring:
    - For BUY: oversold is ideal (1.0), upper-neutral is good continuation (0.8),
               lower-neutral is recovering (0.5), overbought is extended but valid (0.3).
    - For SELL: mirror of the above.

    Previously, overbought for a BUY returned 0.0 — this incorrectly killed
    strong momentum-continuation breakouts. Now it returns 0.3 (reduced, not zero).
    """
    if signal_direction == "BUY":
        if result.state == MomentumState.OVERSOLD:
            return 1.0   # Ideal: oversold bounce
        if result.state == MomentumState.BULLISH_NEUTRAL:
            return 0.8   # RSI 50-70: healthy bullish momentum continuation
        if result.state == MomentumState.BEARISH_NEUTRAL:
            return 0.5   # RSI 30-50: recovering, below midpoint
        # OVERBOUGHT (RSI > 70): extended move, caution but not disqualified
        return 0.3

    else:  # SELL
        if result.state == MomentumState.OVERBOUGHT:
            return 1.0   # Ideal: overbought reversal
        if result.state == MomentumState.BEARISH_NEUTRAL:
            return 0.8   # RSI 30-50: healthy bearish momentum continuation
        if result.state == MomentumState.BULLISH_NEUTRAL:
            return 0.5   # RSI 50-70: recovering upward (mildly against SELL)
        # OVERSOLD (RSI < 30): extended downmove, caution but not disqualified
        return 0.3
