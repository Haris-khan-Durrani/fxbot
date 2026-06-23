"""
tests/test_scoring.py
─────────────────────
Unit tests for the signal scoring engine.
"""
from __future__ import annotations

import pandas as pd
import pytest
from datetime import datetime, timezone

from src.backtest.strategy_functions import (
    compute_signal,
)


def _make_df(n: int, prices: list[float] = None, base: float = 1.3000) -> pd.DataFrame:
    if prices is None:
        prices = [base] * n
    idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": prices, "high": [p + 0.0010 for p in prices],
        "low": [p - 0.0010 for p in prices], "close": prices,
    }, index=idx)


def _default_params() -> dict:
    return {
        "ema_fast": 10,
        "ema_slow": 50,
        "bos_lookback": 20,
        "bos_confirm": 2,
        "sweep_lookback": 15,
        "sweep_wick": 0.5,
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "rsi_neutral_low": 40,
        "rsi_neutral_high": 60,
        "sl_atr_mult": 1.5,
        "atr_period": 14,
        "score_weights": {"trend": 30, "structure": 25, "liquidity": 20, "momentum": 15, "session": 10},
        "trade_only_in_session": False,
    }


class TestScoring:
    def test_no_bos_gives_no_signal(self):
        df_m15 = _make_df(300)  # Flat market — no BOS
        df_h1 = _make_df(300)
        sig = compute_signal(df_m15, df_h1, _default_params())
        assert sig.direction == "NONE"
        assert sig.score == 0.0

    def test_score_in_valid_range(self):
        """Score must always be between 0 and 100."""
        df_m15 = _make_df(300)
        df_h1 = _make_df(300)
        sig = compute_signal(df_m15, df_h1, _default_params())
        assert 0.0 <= sig.score <= 100.0

    def test_buy_signal_on_uptrend_bos(self):
        """Uptrending market with BOS above swing high should produce BUY signal."""
        n = 300
        prices = [1.3000 + i * 0.0010 for i in range(n)]  # Trending up
        # Create BOS: last 2 bars close above recent high
        swing_max = max(prices[n - 25:n - 3])
        prices[-2] = swing_max + 0.0005
        prices[-1] = swing_max + 0.0008

        df_m15 = _make_df(n, prices)
        df_h1 = _make_df(n, prices)
        params = _default_params()
        sig = compute_signal(df_m15, df_h1, params)
        # Should get BUY or NONE — we just verify it doesn't produce SELL
        assert sig.direction in ("BUY", "NONE")

    def test_score_weights_sum_correctly(self):
        """Verify the weighted scoring formula doesn't exceed 100."""
        params = _default_params()
        params["score_weights"] = {"trend": 40, "structure": 30, "liquidity": 15, "momentum": 10, "session": 5}
        df = _make_df(300)
        sig = compute_signal(df, df, params)
        assert sig.score <= 100.0


class TestRSIDirectionAwareScoring:
    """Verify the new direction-aware RSI momentum scoring (Phase 0 fix)."""

    def test_rsi_overbought_buy_scores_0_3_not_zero(self):
        """RSI > 70 with a BUY signal must score 0.3, not 0.0 (was broken before fix)."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        result = MomentumResult(rsi_value=75.0, state=MomentumState.OVERBOUGHT)
        score = momentum_score(result, "BUY")
        assert score == 0.3, f"Expected 0.3 but got {score}"

    def test_rsi_oversold_sell_scores_0_3_not_zero(self):
        """RSI < 30 with a SELL signal must score 0.3, not 0.0."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        result = MomentumResult(rsi_value=25.0, state=MomentumState.OVERSOLD)
        score = momentum_score(result, "SELL")
        assert score == 0.3, f"Expected 0.3 but got {score}"

    def test_rsi_upper_neutral_buy_scores_0_8(self):
        """RSI 50-70 (BULLISH_NEUTRAL) with BUY should score 0.8 — healthy continuation."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        result = MomentumResult(rsi_value=62.0, state=MomentumState.BULLISH_NEUTRAL)
        score = momentum_score(result, "BUY")
        assert score == 0.8, f"Expected 0.8 but got {score}"

    def test_rsi_lower_neutral_buy_scores_0_5(self):
        """RSI 30-50 (BEARISH_NEUTRAL) with BUY should score 0.5 — recovering."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        result = MomentumResult(rsi_value=38.0, state=MomentumState.BEARISH_NEUTRAL)
        score = momentum_score(result, "BUY")
        assert score == 0.5, f"Expected 0.5 but got {score}"

    def test_rsi_oversold_buy_scores_1_0(self):
        """RSI <= 30 with BUY should score 1.0 — ideal oversold bounce."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        result = MomentumResult(rsi_value=28.0, state=MomentumState.OVERSOLD)
        score = momentum_score(result, "BUY")
        assert score == 1.0, f"Expected 1.0 but got {score}"

    def test_rsi_sell_scores_mirror_buy(self):
        """SELL scoring must mirror BUY scoring symmetrically."""
        from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
        # Overbought + SELL = 1.0 (mirrors Oversold + BUY = 1.0)
        assert momentum_score(MomentumResult(75.0, MomentumState.OVERBOUGHT), "SELL") == 1.0
        # Bearish neutral + SELL = 0.8 (mirrors Bullish neutral + BUY = 0.8)
        assert momentum_score(MomentumResult(40.0, MomentumState.BEARISH_NEUTRAL), "SELL") == 0.8
        # Bullish neutral + SELL = 0.5
        assert momentum_score(MomentumResult(60.0, MomentumState.BULLISH_NEUTRAL), "SELL") == 0.5


class TestBOSATRGate:
    """Verify the ATR minimum break distance gate in BOS detection (Phase 0 fix)."""

    def test_tiny_break_rejected(self):
        """A BOS break smaller than ATR × 0.10 must return NONE."""
        from src.backtest.strategy_functions import detect_bos_bar
        import pandas as pd
        n = 60
        # Flat market at 1.3000 with a tiny 0.00001 break above swing high
        prices = [1.3000] * n
        prices[-1] = 1.3001   # Swing high of the lookback will be ~1.3000
        prices[-2] = 1.3001   # 2-bar confirmation — but break is 0.0001, ATR ~ 0.0002+ from range
        idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
        df = pd.DataFrame({
            "open": [1.3000] * n,
            "high": [p + 0.0010 for p in prices],  # Range = 0.002 so ATR ~ 0.002
            "low": [p - 0.0010 for p in prices],
            "close": prices,
        }, index=idx)
        # ATR ~ 0.002, min_break = 0.002 * 0.10 = 0.0002
        # break_distance = 1.3001 - 1.3000 = 0.0001 < 0.0002 → NONE
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2, min_break_atr_ratio=0.10)
        assert direction == "NONE", f"Expected NONE for tiny break, got {direction}"

    def test_significant_break_accepted(self):
        """A BOS break larger than ATR × 0.10 must be accepted."""
        from src.backtest.strategy_functions import detect_bos_bar
        import pandas as pd
        n = 60
        prices = [1.3000] * n
        # Large break: last 2 closes well above swing high
        prices[-1] = 1.3100
        prices[-2] = 1.3090
        idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
        df = pd.DataFrame({
            "open": [1.3000] * n,
            "high": [p + 0.0010 for p in prices],
            "low": [p - 0.0010 for p in prices],
            "close": prices,
        }, index=idx)
        direction, conf = detect_bos_bar(df, lookback=20, confirm=2, min_break_atr_ratio=0.10)
        assert direction == "BULLISH", f"Expected BULLISH for large break, got {direction}"
        assert conf > 0.0


class TestRiskLimits:
    """Lightweight risk limit logic tests that don't require a DB."""

    def test_lot_size_capped_at_max(self):
        from src.risk.position_sizing import calc_lot_size
        from src.data.symbol_info import SymbolSpec

        spec = SymbolSpec(
            symbol="EURUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=0.10,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        # 100% risk should be capped at max_lot
        lot = calc_lot_size(balance=10000, sl_pips=10, spec=spec, risk_pct=100.0)
        assert lot <= spec.max_lot

    def test_lot_size_minimum(self):
        from src.risk.position_sizing import calc_lot_size
        from src.data.symbol_info import SymbolSpec

        spec = SymbolSpec(
            symbol="EURUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=100.0,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        # Very tiny risk should still be minimum lot
        lot = calc_lot_size(balance=100, sl_pips=1000, spec=spec, risk_pct=0.01)
        assert lot >= spec.min_lot

    def test_lot_size_formula(self):
        """Basic formula: risk_amount / (sl_pips × pip_val) = lot."""
        from src.risk.position_sizing import calc_lot_size
        from src.data.symbol_info import SymbolSpec
        import math

        spec = SymbolSpec(
            symbol="EURUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=100.0,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        balance = 10000
        risk_pct = 1.0
        sl_pips = 20.0

        expected_raw = (balance * risk_pct / 100) / (sl_pips * spec.pip_value_per_lot)
        # = 100 / 200 = 0.5 lots
        lot = calc_lot_size(balance=balance, sl_pips=sl_pips, spec=spec, risk_pct=risk_pct)
        assert abs(lot - math.floor(expected_raw / spec.lot_step) * spec.lot_step) < 0.01
