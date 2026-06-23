from __future__ import annotations

from unittest.mock import patch, MagicMock
import pytest
from src.strategy.session_filter import SessionResult, SessionLabel

# We will test the functions from position_monitor and reconciler
from src.execution.position_monitor import _handle_closed_position, _get_close_details_from_history
from src.execution.reconciler import reconcile, sync_closed_deals
import src.execution.reconciler as rec_module


class TestReconciliationAndStats:
    
    @patch("src.execution.position_monitor.repo")
    @patch("src.execution.position_monitor._get_close_details_from_history")
    @patch("src.execution.position_monitor._notify_closed")
    @patch("src.execution.position_monitor._run_ai_post_trade_review")
    def test_position_monitor_records_only_on_successful_close(
        self, mock_ai_review, mock_notify, mock_get_details, mock_repo
    ):
        # Setup mock trade
        trade = MagicMock()
        trade.mt5_ticket = 12345
        trade.symbol = "NZDUSD"
        trade.direction = "SELL"
        trade.open_price = 0.58200
        trade.lot_size = 1.0
        
        session = SessionResult(in_session=True, label=SessionLabel.LONDON, score=0.7)
        
        # Case 1: repo.close_trade returns None (already closed by another process)
        mock_get_details.return_value = (0.58150, 50.0, "TP")
        mock_repo.close_trade.return_value = None
        
        _handle_closed_position(trade, session)
        
        mock_repo.close_trade.assert_called_once()
        mock_repo.record_trade_result.assert_not_called()
        mock_notify.assert_not_called()
        mock_ai_review.assert_not_called()
        
        # Reset mocks
        mock_repo.close_trade.reset_mock()
        mock_repo.record_trade_result.reset_mock()
        mock_notify.reset_mock()
        mock_ai_review.reset_mock()
        
        # Case 2: repo.close_trade succeeds (returns a trade history object)
        mock_repo.close_trade.return_value = MagicMock()
        
        _handle_closed_position(trade, session)
        
        mock_repo.close_trade.assert_called_once()
        mock_repo.record_trade_result.assert_called_once_with(50.0)
        mock_notify.assert_called_once()
        mock_ai_review.assert_called_once()

    @patch("src.execution.reconciler.repo")
    @patch("src.execution.reconciler.get_open_positions")
    @patch("MetaTrader5.history_deals_get")
    @patch("src.execution.reconciler.sync_closed_deals")
    def test_reconciler_reconcile_records_only_on_successful_close(
        self, mock_sync, mock_deals_get, mock_get_open_pos, mock_repo
    ):
        rec_module._last_reconcile = 0.0  # Reset rate limiting
        mock_get_open_pos.return_value = []  # No open positions in MT5
        
        # Setup mock db trade (which is now an orphan)
        trade = MagicMock()
        trade.mt5_ticket = 67890
        trade.symbol = "EURUSD"
        trade.direction = "BUY"
        trade.open_price = 1.10000
        trade.lot_size = 1.0
        
        mock_repo.get_open_trades.return_value = [trade]
        
        # Mock MT5 deal history for the orphan
        deal_mock = MagicMock()
        deal_mock.entry = 1  # DEAL_ENTRY_OUT
        deal_mock.price = 1.10100
        deal_mock.profit = 100.0
        deal_mock.swap = 0.0
        deal_mock.commission = -2.0
        deal_mock.reason = 3  # DEAL_REASON_SL
        
        mock_deals_get.return_value = [deal_mock]
        
        # Case 1: repo.close_trade returns None
        mock_repo.close_trade.return_value = None
        
        reconcile()
        
        mock_repo.close_trade.assert_called_once()
        mock_repo.record_trade_result.assert_not_called()
        
        # Reset rate limiting and mocks
        rec_module._last_reconcile = 0.0
        mock_repo.close_trade.reset_mock()
        mock_repo.record_trade_result.reset_mock()
        
        # Case 2: repo.close_trade succeeds
        mock_repo.close_trade.return_value = MagicMock()
        
        reconcile()
        
        mock_repo.close_trade.assert_called_once()
        # Profit (100) + Swap (0) + Comm (-2) = 98.0
        mock_repo.record_trade_result.assert_called_once_with(98.0)

    @patch("MetaTrader5.history_deals_get")
    def test_get_close_details_from_history(self, mock_deals_get):
        # Case 1: No deals
        mock_deals_get.return_value = None
        price, pnl, reason = _get_close_details_from_history(12345)
        assert price is None
        assert pnl is None
        assert reason is None
        
        # Case 2: Standard close deal exists
        deal_mock = MagicMock()
        deal_mock.entry = 1  # DEAL_ENTRY_OUT
        deal_mock.price = 1.2345
        deal_mock.profit = 250.0
        deal_mock.swap = 5.0
        deal_mock.commission = -1.5
        deal_mock.reason = 3  # DEAL_REASON_SL (SL hit)
        
        mock_deals_get.return_value = [deal_mock]
        
        # Mock MetaTrader5 module constants
        with patch("MetaTrader5.DEAL_ENTRY_OUT", 1), \
             patch("MetaTrader5.DEAL_REASON_SL", 3):
            price, pnl, reason = _get_close_details_from_history(12345)
            assert price == 1.2345
            assert pnl == 253.5  # 250.0 + 5.0 - 1.5
            assert reason == "SL"

    @patch("src.execution.reconciler.repo")
    @patch("MetaTrader5.terminal_info")
    @patch("MetaTrader5.history_deals_get")
    def test_sync_closed_deals_casts_to_int(self, mock_deals_get, mock_term_info, mock_repo):
        rec_module._last_sync = 0.0  # Reset rate limiting
        mock_term_info.return_value = MagicMock()  # connected
        
        # Mock a deal from history with a float position_id (like from numpy or MT5 wrapper)
        deal_mock = MagicMock()
        deal_mock.entry = 1  # DEAL_ENTRY_OUT
        deal_mock.position_id = 9999.0  # Float type
        deal_mock.price = 1.0
        deal_mock.profit = 10.0
        deal_mock.swap = 0.0
        deal_mock.commission = 0.0
        
        mock_deals_get.return_value = [deal_mock]
        
        # Mock DB session queries
        session_mock = MagicMock()
        mock_repo.session_scope.return_value.__enter__.return_value = session_mock
        
        # Mock database query results to return None (falsy) on first() so we check both tables
        query_history_mock = MagicMock()
        query_history_mock.filter_by.return_value.first.return_value = None
        
        query_trade_mock = MagicMock()
        query_trade_mock.filter_by.return_value.first.return_value = None
        
        session_mock.query.side_effect = lambda model: (
            query_history_mock if model.__name__ == "TradeHistory" else query_trade_mock
        )
        
        with patch("MetaTrader5.DEAL_ENTRY_OUT", 1):
            sync_closed_deals()
            
            # Check that query on TradeHistory and Trade filtered using the integer cast of 9999.0
            query_history_mock.filter_by.assert_called_once_with(mt5_ticket=9999)
            query_trade_mock.filter_by.assert_called_once_with(mt5_ticket=9999)
