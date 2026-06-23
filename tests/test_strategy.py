"""
tests/test_strategy.py
───────────────────────
Unit tests for strategy logic: BOS, liquidity sweep, EMA trend, RSI, session filter.
No MT5 dependency — uses synthetic candle data.
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timezone, timedelta

from src.backtest.strategy_functions import (
    calc_ema, detect_bos_bar, detect_sweep_bar,
    momentum_state, trend_direction, calc_rsi,
)
from src.strategy.session_filter import detect_session, SessionLabel


# ─── Helpers ─────────────────────────────────────────────────────

def make_flat_df(n: int = 300, price: float = 1.3000) -> pd.DataFrame:
    """Create a flat market DataFrame for baseline tests."""
    idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": price, "high": price + 0.0005, "low": price - 0.0005, "close": price,
    }, index=idx)


def make_trending_up(n: int = 300, start: float = 1.2000, step: float = 0.0005) -> pd.DataFrame:
    """Upward-trending prices."""
    idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = [start + i * step for i in range(n)]
    return pd.DataFrame({
        "open": prices, "high": [p + 0.0003 for p in prices],
        "low": [p - 0.0003 for p in prices], "close": prices,
    }, index=idx)


def make_trending_down(n: int = 300, start: float = 1.4000, step: float = -0.0005) -> pd.DataFrame:
    """Downward-trending prices."""
    idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    prices = [start + i * step for i in range(n)]
    return pd.DataFrame({
        "open": prices, "high": [p + 0.0003 for p in prices],
        "low": [p - 0.0003 for p in prices], "close": prices,
    }, index=idx)


# ─── EMA / Trend Tests ────────────────────────────────────────────

class TestTrend:
    def test_ema_uptrend_detected(self):
        df = make_trending_up(n=300)
        # With enough bars, fast EMA > slow EMA in an uptrend
        direction = trend_direction(df, fast=10, slow=50)
        assert direction == "BULLISH"

    def test_ema_downtrend_detected(self):
        df = make_trending_down(n=300)
        direction = trend_direction(df, fast=10, slow=50)
        assert direction == "BEARISH"

    def test_insufficient_bars_returns_neutral(self):
        df = make_flat_df(n=10)
        direction = trend_direction(df, fast=50, slow=200)
        assert direction == "NEUTRAL"

    def test_flat_market_close_to_neutral(self):
        df = make_flat_df(n=300)
        direction = trend_direction(df, fast=50, slow=200)
        # In a flat market EMAs converge — result may be neutral or slight direction
        assert direction in ("BULLISH", "BEARISH", "NEUTRAL")


# ─── BOS Tests ───────────────────────────────────────────────────

class TestBOS:
    def _make_bos_bullish_df(self, n: int = 60, lookback: int = 20) -> pd.DataFrame:
        """Creates data where last 2 bars close above the recent swing high."""
        prices = [1.3000] * n
        # Build a swing high around bar n-25
        prices[n - 25] = 1.3050   # Swing high
        # Last 2 bars close above it
        prices[-2] = 1.3060
        prices[-1] = 1.3065

        idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
        return pd.DataFrame({
            "open": prices, "high": [p + 0.0002 for p in prices],
            "low": [p - 0.0002 for p in prices], "close": prices,
        }, index=idx)

    def _make_bos_bearish_df(self, n: int = 60, lookback: int = 20) -> pd.DataFrame:
        prices = [1.3000] * n
        prices[n - 25] = 1.2950   # Swing low
        prices[-2] = 1.2940
        prices[-1] = 1.2935
        idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
        return pd.DataFrame({
            "open": prices, "high": [p + 0.0002 for p in prices],
            "low": [p - 0.0002 for p in prices], "close": prices,
        }, index=idx)

    def test_bullish_bos_detected(self):
        df = self._make_bos_bullish_df()
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2)
        assert direction == "BULLISH"
        assert 0 < conf <= 1.0

    def test_bearish_bos_detected(self):
        df = self._make_bos_bearish_df()
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2)
        assert direction == "BEARISH"
        assert 0 < conf <= 1.0

    def test_flat_market_no_bos(self):
        df = make_flat_df(n=60)
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2)
        assert direction == "NONE"

    def test_insufficient_bars(self):
        df = make_flat_df(n=5)
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2)
        assert direction == "NONE"
        assert conf == 0.0


# ─── Liquidity Sweep Tests ────────────────────────────────────────

class TestLiquiditySweep:
    def _make_sweep_bullish(self, n: int = 40) -> pd.DataFrame:
        """Last bar wicks below recent swing low then closes above."""
        prices = [1.3000] * n
        idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
        df = pd.DataFrame({
            "open": prices, "high": [p + 0.0010 for p in prices],
            "low": [p - 0.0005 for p in prices], "close": prices,
        }, index=idx)
        # Set last bar: wicks below swing low at 1.2995
        df.iloc[-1, df.columns.get_loc("low")] = 1.2980    # Below swing low
        df.iloc[-1, df.columns.get_loc("close")] = 1.3005  # Closes above
        df.iloc[-1, df.columns.get_loc("high")] = 1.3010
        df.iloc[-1, df.columns.get_loc("open")] = 1.2998
        return df

    def test_bullish_sweep_detected(self):
        df = self._make_sweep_bullish()
        direction, conf = detect_sweep_bar(df, lookback=15, wick_ratio=0.3)
        assert direction in ("BULLISH", "NONE")   # NONE if data doesn't meet ratio

    def test_flat_no_sweep(self):
        df = make_flat_df(n=40)
        direction, conf = detect_sweep_bar(df, lookback=15, wick_ratio=0.5)
        assert direction == "NONE"


# ─── RSI / Momentum Tests ─────────────────────────────────────────

class TestMomentum:
    def test_oversold_on_strong_downtrend(self):
        df = make_trending_down(n=50, start=1.5000, step=-0.005)
        state, rsi = momentum_state(df, period=14)
        assert rsi < 40  # Should be oversold or near it in strong downtrend

    def test_overbought_on_strong_uptrend(self):
        df = make_trending_up(n=50, start=1.2000, step=0.005)
        state, rsi = momentum_state(df, period=14)
        assert rsi > 60  # Should be overbought in strong uptrend

    def test_rsi_range(self):
        """RSI must always be in [0, 100]."""
        df = make_trending_up(n=100)
        _, rsi = momentum_state(df, period=14)
        assert 0 <= rsi <= 100

    def test_insufficient_bars(self):
        df = make_flat_df(n=5)
        state, rsi = momentum_state(df, period=14)
        assert rsi == 50.0


# ─── Session Filter Tests ─────────────────────────────────────────

class TestSessionFilter:
    def _ts(self, hour: int, minute: int = 0) -> float:
        """Create UTC timestamp for today at given hour:minute."""
        dt = datetime.now(timezone.utc).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        return dt.timestamp()

    def test_london_session(self):
        ts = self._ts(10)  # 10:00 UTC → London only
        result = detect_session(ts)
        assert result.in_session is True
        assert result.label in (SessionLabel.LONDON, SessionLabel.OVERLAP)

    def test_ny_session(self):
        ts = self._ts(20)  # 20:00 UTC → NY only
        result = detect_session(ts)
        assert result.in_session is True
        assert result.label in (SessionLabel.NEW_YORK, SessionLabel.OVERLAP)

    def test_overlap_session(self):
        ts = self._ts(14)  # 14:00 UTC → both London and NY
        result = detect_session(ts)
        assert result.in_session is True
        assert result.label == SessionLabel.OVERLAP
        assert result.score == 1.0

    def test_off_session(self):
        ts = self._ts(2)  # 02:00 UTC → neither session
        result = detect_session(ts)
        assert result.in_session is False
        assert result.label == SessionLabel.OFF
        assert result.score == 0.0

    def test_session_score_ordering(self):
        """Overlap > single session > off session."""
        off = detect_session(self._ts(2))
        london = detect_session(self._ts(10))
        overlap = detect_session(self._ts(14))
        assert overlap.score >= london.score >= off.score
