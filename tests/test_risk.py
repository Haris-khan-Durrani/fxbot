"""
tests/test_risk.py
──────────────────
Unit tests for risk management functions:
- Position sizing
- USD exposure limits
- Risk limit rules (mocking repo/database calls)
- Trailing stop & Break-even triggers
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
import pandas as pd

from src.risk.position_sizing import calc_lot_size
from src.risk.exposure import check_usd_exposure, calc_notional_usd
from src.risk.limits import (
    check_all_limits,
    _check_emergency_stop,
    _check_open_trades,
    _check_daily_trade_count,
    _check_daily_loss,
    _check_weekly_loss,
    _check_spread,
    LimitCheckResult,
)
from src.risk.trailing import (
    calc_break_even_level,
    should_trigger_break_even,
    calc_trailing_sl,
    should_trigger_trailing,
)
from src.data.symbol_info import SymbolSpec
from src.data.account_info import OpenPosition


class TestPositionSizing:
    def test_calc_lot_size_normal(self):
        spec = SymbolSpec(
            symbol="EURUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=100.0,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        lot = calc_lot_size(balance=10000, sl_pips=20, spec=spec, risk_pct=1.0)
        # 1% of 10000 = 100 USD risk. 100 / (20 * 10) = 0.5 lot
        assert abs(lot - 0.5) < 1e-5

    def test_calc_lot_size_clamps(self):
        spec = SymbolSpec(
            symbol="EURUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=0.10,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        lot = calc_lot_size(balance=10000, sl_pips=20, spec=spec, risk_pct=100.0)
        assert lot == 0.10  # clamped to max_lot

        lot_min = calc_lot_size(balance=100, sl_pips=1000, spec=spec, risk_pct=0.01)
        assert lot_min == 0.01  # clamped to min_lot

    def test_calc_lot_size_nzdusd(self):
        # NZDUSD spec
        spec = SymbolSpec(
            symbol="NZDUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=500.0,
            contract_size=100000, point=0.00001, digits=5,
            spread_raw=2, spread_pips=0.2,
        )
        # 1. On a $100,000 account, risking 1.0% ($1000) with a 3.868 pip stop:
        lot_100k = calc_lot_size(balance=100000, sl_pips=3.868, spec=spec, risk_pct=1.0)
        # 1000 / (3.868 * 10.0) = 25.853 lots -> rounds down to 25.85 lots
        assert abs(lot_100k - 25.85) < 1e-5

        # 2. On a $10,000 account, risking 1.0% ($100) with a 3.868 pip stop:
        lot_10k = calc_lot_size(balance=10000, sl_pips=3.868, spec=spec, risk_pct=1.0)
        # 100 / (3.868 * 10.0) = 2.585 lots -> rounds down to 2.58 lots
        assert abs(lot_10k - 2.58) < 1e-5

        # 3. On a $10,000 account, risking 1.0% ($100) with a 39.0 pip stop:
        lot_39pip = calc_lot_size(balance=10000, sl_pips=39.0, spec=spec, risk_pct=1.0)
        # 100 / (39.0 * 10.0) = 0.256 lots -> rounds down to 0.25 lots (user expected ~0.26)
        assert abs(lot_39pip - 0.25) < 1e-5

    def test_calc_lot_size_xauusd(self):
        # Intended dynamic pip_value = $10.00 per pip per lot
        spec_new = SymbolSpec(
            symbol="XAUUSD", pip_value_per_lot=10.0,
            lot_step=0.01, min_lot=0.01, max_lot=100.0,
            contract_size=100.0, point=0.01, digits=2,
            spread_raw=30, spread_pips=3.0,
        )
        # Buggy pip_value = $1.00 per pip per lot
        spec_buggy = SymbolSpec(
            symbol="XAUUSD", pip_value_per_lot=1.0,
            lot_step=0.01, min_lot=0.01, max_lot=100.0,
            contract_size=100.0, point=0.01, digits=2,
            spread_raw=30, spread_pips=3.0,
        )
        
        # Risking 1% ($1000) on a $100k account with a 50-pip stop:
        lot_new = calc_lot_size(balance=100000, sl_pips=50.0, spec=spec_new, risk_pct=1.0)
        lot_buggy = calc_lot_size(balance=100000, sl_pips=50.0, spec=spec_buggy, risk_pct=1.0)
        
        # New: 1000 / (50.0 * 10.0) = 2.00 lots
        assert abs(lot_new - 2.00) < 1e-5
        # Buggy: 1000 / (50.0 * 1.0) = 20.00 lots (10x larger)
        assert abs(lot_buggy - 20.00) < 1e-5
        assert lot_new != lot_buggy
        assert lot_buggy / lot_new == 10.0


class TestUSDExposure:
    def test_calc_notional_usd(self):
        pos = OpenPosition(
            ticket=123, symbol="EURUSD", volume=0.5,
            direction="BUY", open_price=1.1000, current_price=1.1050,
            sl=1.0900, tp=1.1200, profit=250.0,
            swap=0.0, comment="",
        )
        notional = calc_notional_usd(pos, 100000, 1.1050)
        # volume (0.5) * contract_size (100000) * price (1.1050) = 55250.0
        assert notional == 55250.0

    def test_check_usd_exposure_allowed(self):
        specs = {
            "EURUSD": SymbolSpec(
                symbol="EURUSD", pip_value_per_lot=10.0,
                lot_step=0.01, min_lot=0.01, max_lot=100.0,
                contract_size=100000, point=0.00001, digits=5,
                spread_raw=2, spread_pips=0.2,
            )
        }
        open_pos = [
            OpenPosition(
                ticket=123, symbol="EURUSD", volume=0.1,
                direction="BUY", open_price=1.1000, current_price=1.1000,
                sl=1.0900, tp=1.1200, profit=0.0,
                swap=0.0, comment="",
            )
        ]
        # total exposure is 0.1 * 100000 * 1.1 = 11000. Limit is 50000.
        allowed, msg = check_usd_exposure(open_pos, "EURUSD", 0.1, specs)
        assert allowed is True
        assert msg == ""

    @patch("src.risk.exposure.get")
    def test_check_usd_exposure_blocked(self, mock_get):
        mock_get.return_value = 15000
        specs = {
            "EURUSD": SymbolSpec(
                symbol="EURUSD", pip_value_per_lot=10.0,
                lot_step=0.01, min_lot=0.01, max_lot=100.0,
                contract_size=100000, point=0.00001, digits=5,
                spread_raw=1.1000, spread_pips=0.2,
            )
        }
        open_pos = [
            OpenPosition(
                ticket=123, symbol="EURUSD", volume=0.1,
                direction="BUY", open_price=1.1000, current_price=1.1000,
                sl=1.0900, tp=1.1200, profit=0.0,
                swap=0.0, comment="",
            )
        ]
        # existing exposure = 11000
        # new proposed exposure = 0.1 lots * 100000 * 1.1000 = 11000 -> total = 22000 > 15000
        allowed, msg = check_usd_exposure(open_pos, "EURUSD", 0.1, specs)
        assert allowed is False
        assert "exposure check failed" in msg


class TestRiskLimitsRules:
    @patch("src.risk.limits.repo.is_emergency_stop")
    def test_emergency_stop_check(self, mock_stop):
        mock_stop.return_value = True
        res = _check_emergency_stop()
        assert res.allowed is False
        assert "Emergency stop" in res.reason

        mock_stop.return_value = False
        res = _check_emergency_stop()
        assert res.allowed is True

    @patch("src.risk.limits.repo.count_open_trades")
    @patch("src.risk.limits.get")
    def test_open_trades_check(self, mock_get, mock_count):
        mock_get.return_value = 1
        mock_count.return_value = 1
        res = _check_open_trades()
        assert res.allowed is False
        assert "Max open trades reached" in res.reason

        mock_count.return_value = 0
        res = _check_open_trades()
        assert res.allowed is True

    @patch("src.risk.limits.repo.get_today_trade_count")
    @patch("src.risk.limits.get")
    def test_daily_trade_count_check(self, mock_get, mock_count):
        mock_get.return_value = 2
        mock_count.return_value = 2
        res = _check_daily_trade_count()
        assert res.allowed is False
        assert "Daily trade limit reached" in res.reason

        mock_count.return_value = 1
        res = _check_daily_trade_count()
        assert res.allowed is True

    @patch("src.risk.limits.repo.get_today_pnl")
    @patch("src.risk.limits.repo.log_system_event")
    @patch("src.risk.limits.get")
    def test_daily_loss_check(self, mock_get, mock_log, mock_pnl):
        mock_get.return_value = 3.0
        # Positive PnL: allowed
        mock_pnl.return_value = 100.0
        res = _check_daily_loss(10000)
        assert res.allowed is True

        # Loss within limit: allowed
        mock_pnl.return_value = -200.0
        res = _check_daily_loss(10000)
        assert res.allowed is True

        # Loss exceeding limit
        mock_pnl.return_value = -400.0
        res = _check_daily_loss(10000)
        assert res.allowed is False
        assert "Daily loss limit hit" in res.reason

    @patch("src.risk.limits.get_current_spread_pips")
    @patch("src.risk.limits.get")
    def test_spread_check(self, mock_get, mock_spread):
        mock_get.return_value = {"EURUSD": 2.0}
        mock_spread.return_value = 2.5
        res = _check_spread("EURUSD")
        assert res.allowed is False
        assert "spread too wide" in res.reason

        mock_spread.return_value = 1.5
        res = _check_spread("EURUSD")
        assert res.allowed is True


class TestRiskTrailing:
    def test_calc_break_even_level(self):
        class MockTrade:
            symbol = "EURUSD"
            direction = "BUY"
            open_price = 1.1000

        class MockSpec:
            point = 0.00001

        trade = MockTrade()
        spec = MockSpec()
        level = calc_break_even_level(trade, spec)
        # buffer_pips = 1.0 -> price distance = 1.0 * 0.00001 * 10 = 0.0001
        # BUY: entry + buffer = 1.1000 + 0.0001 = 1.1001
        assert abs(level - 1.1001) < 1e-5

        trade.direction = "SELL"
        level = calc_break_even_level(trade, spec)
        # SELL: entry - buffer = 1.1000 - 0.0001 = 1.0999
        assert abs(level - 1.0999) < 1e-5

    @patch("src.risk.trailing.get")
    def test_should_trigger_break_even(self, mock_get):
        mock_get.return_value = 1.0  # RR = 1.0

        pos = OpenPosition(
            ticket=123, symbol="EURUSD", volume=0.1,
            direction="BUY", open_price=1.1000, current_price=1.1010,
            sl=1.1000, tp=1.1200, profit=0.0,
            swap=0.0, comment="",
        )

        class MockTrade:
            break_even_triggered = False
            open_price = 1.1000
            sl_price = 1.0990  # 10 pips SL distance

        trade = MockTrade()
        class MockSpec:
            pass

        assert should_trigger_break_even(pos, trade, MockSpec()) is True

        pos.current_price = 1.1009
        assert should_trigger_break_even(pos, trade, MockSpec()) is False

    @patch("src.risk.trailing.get")
    def test_calc_trailing_sl(self, mock_get):
        mock_get.return_value = 1.5  # multiplier = 1.5
        pos = OpenPosition(
            ticket=123, symbol="EURUSD", volume=0.1,
            direction="BUY", open_price=1.1000, current_price=1.1050,
            sl=1.0900, tp=1.1200, profit=0.0,
            swap=0.0, comment="",
        )
        class MockSpec:
            pass
        new_sl = calc_trailing_sl(pos, 1.0900, MockSpec(), 0.0020)
        assert abs(new_sl - 1.1020) < 1e-5

        new_sl_worse = calc_trailing_sl(pos, 1.1030, MockSpec(), 0.0020)
        assert new_sl_worse == 1.1030

    @patch("src.risk.trailing.get")
    def test_should_trigger_trailing(self, mock_get):
        mock_get.return_value = 1.5  # trigger_rr = 1.5
        pos = OpenPosition(
            ticket=123, symbol="EURUSD", volume=0.1,
            direction="BUY", open_price=1.1000, current_price=1.1015,
            sl=1.0990, tp=1.1200, profit=0.0,
            swap=0.0, comment="",
        )
        class MockTrade:
            open_price = 1.1000
            sl_price = 1.0990  # 10 pips SL distance

        trade = MockTrade()
        # sl_distance = 10 pips. trigger_distance = 15 pips (0.0015).
        # current profit = 15 pips (0.0015) -> triggers
        assert should_trigger_trailing(pos, trade) is True

        pos.current_price = 1.1014
        assert should_trigger_trailing(pos, trade) is False


class TestOrderManagerSafetyCeiling:
    @patch("src.execution.order_manager.get")
    @patch("src.execution.order_manager.repo.trigger_emergency_stop")
    @patch("src.execution.order_manager.MT5_AVAILABLE", True)
    def test_open_trade_exceeds_max_lot(self, mock_trigger, mock_get):
        from src.execution.order_manager import open_trade
        # Mock risk config max lot size limits
        mock_get.return_value = {"EURUSD": 2.0}
        
        # Placing 2.5 lots of EURUSD (limit is 2.0)
        res = open_trade("EURUSD", "BUY", 2.5, 1.1000, 1.1200)
        
        assert res.success is False
        assert "exceeds max allowed limit" in res.error
        # Verify emergency stop triggered
        mock_trigger.assert_called_once()

    @patch("src.execution.order_manager.get")
    @patch("src.execution.order_manager.repo.trigger_emergency_stop")
    @patch("src.execution.order_manager.MT5_AVAILABLE", True)
    @patch("src.execution.order_manager._live_trading_guard")
    @patch("src.execution.order_manager.mt5")
    def test_open_trade_within_max_lot(self, mock_mt5, mock_guard, mock_trigger, mock_get):
        from src.execution.order_manager import open_trade
        # Mock risk config max lot size limits
        mock_get.return_value = {"EURUSD": 2.0}
        mock_guard.return_value = True
        
        # Mock MT5 order_send success
        mock_mt5.symbol_info_tick.return_value.ask = 1.1000
        mock_mt5.symbol_info_tick.return_value.bid = 1.1000
        mock_mt5.order_send.return_value.retcode = 10009  # TRADE_RETCODE_DONE
        mock_mt5.order_send.return_value.order = 99999
        mock_mt5.TRADE_ACTION_DEAL = 1
        mock_mt5.ORDER_TIME_GTC = 1
        mock_mt5.ORDER_FILLING_FOK = 1
        mock_mt5.symbol_info.return_value.filling_mode = 1
        mock_mt5.TRADE_RETCODE_DONE = 10009
        
        # Placing 1.5 lots of EURUSD (limit is 2.0)
        res = open_trade("EURUSD", "BUY", 1.5, 1.0900, 1.1200)
        
        assert res.success is True
        assert res.ticket == 99999
        # Verify emergency stop was NOT triggered
        mock_trigger.assert_not_called()

