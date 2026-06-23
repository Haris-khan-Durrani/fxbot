"""
src/backtest/strategy_functions.py
────────────────────────────────────
Pure, stateless strategy functions for backtesting.
No live MT5 dependencies — only pandas/numpy.
These are the same logic as src/strategy/* but adapted for bar-by-bar simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

# ── Trend ─────────────────────────────────────────────────────────

def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def trend_direction(df_h1: pd.DataFrame, fast: int = 50, slow: int = 200) -> str:
    """Returns 'BULLISH', 'BEARISH', or 'NEUTRAL' based on EMA cross."""
    if len(df_h1) < slow:
        return "NEUTRAL"
    ema_fast = calc_ema(df_h1["close"], fast).iloc[-1]
    ema_slow = calc_ema(df_h1["close"], slow).iloc[-1]
    if ema_fast > ema_slow:
        return "BULLISH"
    elif ema_fast < ema_slow:
        return "BEARISH"
    return "NEUTRAL"


# ── BOS ───────────────────────────────────────────────────────────

def detect_bos_bar(df_m15: pd.DataFrame, lookback: int = 20, confirm: int = 2,
                   min_break_atr_ratio: float = 0.10, atr_period: int = 14) -> tuple[str, float]:
    """
    Returns (direction, confidence): direction in ['BULLISH', 'BEARISH', 'NONE'].
    Break distance must be ≥ ATR(atr_period) × min_break_atr_ratio to filter noise.
    """
    if len(df_m15) < lookback + confirm + 3:
        return "NONE", 0.0

    swing_high = df_m15["high"].iloc[-(lookback + 2):-2].max()
    swing_low = df_m15["low"].iloc[-(lookback + 2):-2].min()

    recent_closes = df_m15["close"].iloc[-confirm:]
    candle_range = df_m15["high"].iloc[-1] - df_m15["low"].iloc[-1]
    if candle_range < 1e-10:
        return "NONE", 0.0

    # ATR for minimum break distance gate
    atr = float(calc_atr(df_m15, atr_period).iloc[-1]) if len(df_m15) > atr_period else 0.0
    min_break = atr * min_break_atr_ratio

    if all(recent_closes > swing_high):
        break_dist = float(recent_closes.iloc[-1] - swing_high)
        if break_dist < min_break:
            return "NONE", 0.0
        conf = min(1.0, break_dist / candle_range)
        return "BULLISH", max(0.5, conf)
    if all(recent_closes < swing_low):
        break_dist = float(swing_low - recent_closes.iloc[-1])
        if break_dist < min_break:
            return "NONE", 0.0
        conf = min(1.0, break_dist / candle_range)
        return "BEARISH", max(0.5, conf)
    return "NONE", 0.0


# ── Liquidity Sweep ───────────────────────────────────────────────

def detect_sweep_bar(df_m15: pd.DataFrame, lookback: int = 20, wick_ratio: float = 0.5) -> tuple[str, float]:
    """
    Returns (direction, confidence). direction: 'BULLISH', 'BEARISH', 'NONE'.
    Bullish = swept lows (expect up). Bearish = swept highs (expect down).
    """
    if len(df_m15) < lookback + 3:
        return "NONE", 0.0

    lookback_slice = df_m15.iloc[-(lookback + 2):-2]
    swing_high = lookback_slice["high"].max()
    swing_low = lookback_slice["low"].min()

    last = df_m15.iloc[-1]
    rng = last["high"] - last["low"]
    if rng < 1e-10:
        return "NONE", 0.0

    # Bullish sweep
    if last["low"] < swing_low and last["close"] > swing_low:
        wick = (swing_low - last["low"]) / rng
        if wick >= wick_ratio:
            return "BULLISH", min(1.0, wick)

    # Bearish sweep
    if last["high"] > swing_high and last["close"] < swing_high:
        wick = (last["high"] - swing_high) / rng
        if wick >= wick_ratio:
            return "BEARISH", min(1.0, wick)

    return "NONE", 0.0


# ── RSI ───────────────────────────────────────────────────────────

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI using Wilder's smoothing (EWM)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    # When avg_loss == 0 (pure uptrend), RS = infinity → RSI = 100
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return (100 - (100 / (1 + rs))).fillna(100)


def momentum_state(df_m15: pd.DataFrame, period: int = 14,
                   oversold: float = 30, overbought: float = 70,
                   rsi_mid: float = 50,
                   neutral_low: float = 40, neutral_high: float = 60) -> tuple[str, float]:
    """Returns (state, rsi_value) where state is OVERSOLD/OVERBOUGHT/BULLISH_NEUTRAL/BEARISH_NEUTRAL.
    Uses rsi_mid (default 50) as the split between BULLISH_NEUTRAL and BEARISH_NEUTRAL zones.
    neutral_low/neutral_high kept as parameters for legacy compatibility.
    """
    if len(df_m15) < period * 2:
        return "NEUTRAL", 50.0
    rsi = float(calc_rsi(df_m15["close"], period).iloc[-1])
    if rsi <= oversold:
        return "OVERSOLD", rsi
    if rsi >= overbought:
        return "OVERBOUGHT", rsi
    if rsi >= rsi_mid:
        return "BULLISH_NEUTRAL", rsi   # 50-70 zone
    return "BEARISH_NEUTRAL", rsi       # 30-50 zone


# ── ATR ───────────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


# ── Signal Scoring (parameterized) ───────────────────────────────

@dataclass
class BacktestSignal:
    direction: str      # BUY | SELL | NONE
    score: float        # 0-100
    sl_distance: float  # Price-based SL distance (ATR × multiplier)
    bos_conf: float
    sweep_conf: float
    rsi_value: float


def compute_signal(
    df_m15: pd.DataFrame,
    df_h1: pd.DataFrame,
    params: dict,
) -> BacktestSignal:
    """
    Compute a signal score at the current bar end.
    Params keys: ema_fast, ema_slow, bos_lookback, bos_confirm,
                 sweep_lookback, sweep_wick, rsi_period, rsi_oversold,
                 rsi_overbought, rsi_neutral_low, rsi_neutral_high,
                 sl_atr_mult, score_weights (dict), min_score.
    """
    p = params

    # Strategy components
    trend = trend_direction(df_h1, p["ema_fast"], p["ema_slow"])
    bos_dir, bos_conf = detect_bos_bar(df_m15, p["bos_lookback"], p["bos_confirm"])
    sweep_dir, sweep_conf = detect_sweep_bar(df_m15, p["sweep_lookback"], p["sweep_wick"])
    mom_state, rsi_val = momentum_state(
        df_m15, p["rsi_period"], p["rsi_oversold"], p["rsi_overbought"],
        rsi_mid=p.get("rsi_mid", 50),
        neutral_low=p.get("rsi_neutral_low", 40),
        neutral_high=p.get("rsi_neutral_high", 60),
    )

    # Direction from BOS
    if bos_dir == "NONE":
        return BacktestSignal("NONE", 0.0, 0.0, 0.0, 0.0, rsi_val)

    direction = "BUY" if bos_dir == "BULLISH" else "SELL"

    # Sweep must agree if detected
    if sweep_dir not in ("NONE", bos_dir):
        return BacktestSignal("NONE", 0.0, 0.0, 0.0, 0.0, rsi_val)

    # Compute component 0-1 scores
    w = p.get("score_weights", {"trend": 30, "structure": 25, "liquidity": 20, "momentum": 15, "session": 10})
    total_w = sum(w.values())

    # Trend alignment
    if trend == "NEUTRAL":
        s_trend = 0.5
    elif (trend == "BULLISH" and direction == "BUY") or (trend == "BEARISH" and direction == "SELL"):
        s_trend = 1.0
    else:
        s_trend = 0.0

    # Structure
    s_structure = bos_conf if ((bos_dir == "BULLISH" and direction == "BUY") or
                               (bos_dir == "BEARISH" and direction == "SELL")) else 0.0

    # Liquidity
    s_liquidity = sweep_conf if sweep_dir != "NONE" and \
                               ((sweep_dir == "BULLISH" and direction == "BUY") or
                                (sweep_dir == "BEARISH" and direction == "SELL")) else 0.0

    # Momentum — direction-aware scoring (mirrors src/strategy/momentum.py)
    if direction == "BUY":
        s_mom_map = {"OVERSOLD": 1.0, "BULLISH_NEUTRAL": 0.8, "BEARISH_NEUTRAL": 0.5, "OVERBOUGHT": 0.3}
    else:
        s_mom_map = {"OVERBOUGHT": 1.0, "BEARISH_NEUTRAL": 0.8, "BULLISH_NEUTRAL": 0.5, "OVERSOLD": 0.3}
    s_momentum = s_mom_map.get(mom_state, 0.5)

    # Session
    s_session = 0.7
    in_session = True

    if hasattr(df_m15.index, "hour") and len(df_m15) > 0:
        last_dt = df_m15.index[-1]
        london_open = p.get("london_open", "08:00")
        london_close = p.get("london_close", "17:00")
        ny_open = p.get("ny_open", "13:00")
        ny_close = p.get("ny_close", "22:00")

        def _to_mins(time_str: str) -> int:
            parts = time_str.split(":")
            return int(parts[0]) * 60 + int(parts[1])

        l_start = _to_mins(london_open)
        l_end = _to_mins(london_close)
        n_start = _to_mins(ny_open)
        n_end = _to_mins(ny_close)

        current_mins = last_dt.hour * 60 + last_dt.minute

        in_london = l_start <= current_mins < l_end
        in_ny = n_start <= current_mins < n_end

        in_session = in_london or in_ny
        if in_london and in_ny:
            s_session = 1.0
        elif in_london or in_ny:
            s_session = 0.7
        else:
            s_session = 0.0

    if p.get("trade_only_in_session", True) and not in_session:
        return BacktestSignal("NONE", 0.0, 0.0, 0.0, 0.0, rsi_val)

    score = (
        s_trend * 100 * w.get("trend", 30) +
        s_structure * 100 * w.get("structure", 25) +
        s_liquidity * 100 * w.get("liquidity", 20) +
        s_momentum * 100 * w.get("momentum", 15) +
        s_session * 100 * w.get("session", 10)
    ) / total_w

    # ATR-based SL distance
    if len(df_m15) > p.get("atr_period", 14):
        atr = float(calc_atr(df_m15, p.get("atr_period", 14)).iloc[-1])
        sl_distance = atr * p.get("sl_atr_mult", 1.5)
    else:
        sl_distance = 0.0

    return BacktestSignal(
        direction=direction,
        score=round(score, 2),
        sl_distance=sl_distance,
        bos_conf=bos_conf,
        sweep_conf=sweep_conf,
        rsi_value=rsi_val,
    )
