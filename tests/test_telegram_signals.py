"""
tests/test_telegram_signals.py
──────────────────────────────
Unit tests for the public Telegram signal channel broadcaster.

Tests:
  1. format_signal_open   — asserts correct fields present, lot/balance absent.
  2. format_signal_close  — asserts result fields present, lot/balance absent.
  3. send_signal_notification failure is swallowed silently (never raises).
  4. When telegram_signals.enabled=false, no send is attempted.
  5. Private notification path is unaffected when signal channel send fails.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.telegram.signal_channel import (
    format_signal_close,
    format_signal_open,
    send_signal_notification,
)


# ── Async helper ──────────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine synchronously, compatible with Python 3.10+."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── 1. format_signal_open ────────────────────────────────────────────────────

class TestFormatSignalOpen:
    def test_contains_entry_sl_tp(self):
        msg = format_signal_open(
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2312.50,
            sl_price=2298.20,
            tp_price=2340.90,
            score=71.2,
            session="LONDON",
        )
        assert "2,312.50" in msg   # entry formatted
        assert "2,298.20" in msg   # SL
        assert "2,340.90" in msg   # TP

    def test_contains_score_when_enabled(self):
        with patch("src.telegram.signal_channel.get", return_value=True):
            msg = format_signal_open(
                symbol="EURUSD",
                direction="BUY",
                entry_price=1.08500,
                sl_price=1.08000,
                tp_price=1.09500,
                score=73.5,
                session="NY",
            )
        assert "73.5" in msg
        assert "Score" in msg

    def test_contains_session_when_enabled(self):
        with patch("src.telegram.signal_channel.get", return_value=True):
            msg = format_signal_open(
                symbol="EURUSD",
                direction="SELL",
                entry_price=1.08500,
                sl_price=1.09000,
                tp_price=1.07500,
                score=68.0,
                session="LONDON/NY OVERLAP",
            )
        assert "LONDON/NY OVERLAP" in msg

    def test_contains_disclaimer(self):
        msg = format_signal_open(
            symbol="GBPUSD",
            direction="BUY",
            entry_price=1.27000,
            sl_price=1.26500,
            tp_price=1.28000,
        )
        assert "Not financial advice" in msg

    def test_does_not_contain_lot_size(self):
        msg = format_signal_open(
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2312.50,
            sl_price=2298.20,
            tp_price=2340.90,
            score=71.2,
            session="LONDON",
        )
        # The string "lot" must never appear in any public signal
        assert "lot" not in msg.lower()

    def test_does_not_contain_balance(self):
        msg = format_signal_open(
            symbol="XAUUSD",
            direction="BUY",
            entry_price=2312.50,
            sl_price=2298.20,
            tp_price=2340.90,
        )
        assert "balance" not in msg.lower()
        assert "equity" not in msg.lower()

    def test_rr_calculated_from_prices(self):
        """RR must be computed from SL/TP distances, not hardcoded."""
        msg = format_signal_open(
            symbol="EURUSD",
            direction="BUY",
            entry_price=1.10000,
            sl_price=1.09800,   # 20 pip SL
            tp_price=1.10400,   # 40 pip TP → RR = 2.0
        )
        assert "2.0" in msg
        assert "RR" in msg

    def test_buy_signal_emoji(self):
        msg = format_signal_open(
            symbol="EURUSD",
            direction="BUY",
            entry_price=1.1000,
            sl_price=1.0980,
            tp_price=1.1040,
        )
        assert "🟢" in msg
        assert "BUY" in msg

    def test_sell_signal_emoji(self):
        msg = format_signal_open(
            symbol="EURUSD",
            direction="SELL",
            entry_price=1.1000,
            sl_price=1.1020,
            tp_price=1.0960,
        )
        assert "🔴" in msg
        assert "SELL" in msg


# ── 2. format_signal_close ───────────────────────────────────────────────────

class TestFormatSignalClose:
    _now = datetime(2026, 6, 19, 11, 28, tzinfo=timezone.utc)
    _opened = datetime(2026, 6, 19, 9, 14, tzinfo=timezone.utc)

    def test_contains_pips_and_pnl(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=28.6,
            pnl_usd=984.20,
            close_reason="TP",
            score=71.2,
            opened_at=self._opened,
            closed_at=self._now,
        )
        assert "28.6" in msg
        assert "984.20" in msg

    def test_contains_reason_tp(self):
        msg = format_signal_close(
            symbol="EURUSD",
            direction="BUY",
            pips=20.0,
            pnl_usd=200.0,
            close_reason="TP",
        )
        assert "TP" in msg

    def test_contains_reason_sl(self):
        msg = format_signal_close(
            symbol="EURUSD",
            direction="BUY",
            pips=-20.0,
            pnl_usd=-200.0,
            close_reason="SL",
        )
        assert "SL" in msg

    def test_contains_reason_tsl(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=15.0,
            pnl_usd=500.0,
            close_reason="TSL",
        )
        assert "Trailing" in msg or "TSL" in msg

    def test_contains_reason_be(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="SELL",
            pips=0.2,
            pnl_usd=5.0,
            close_reason="BE",
        )
        assert "Break-Even" in msg or "BE" in msg

    def test_contains_duration(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=28.6,
            pnl_usd=984.20,
            close_reason="TP",
            opened_at=self._opened,
            closed_at=self._now,
        )
        assert "2h 14m" in msg

    def test_contains_score(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=28.6,
            pnl_usd=984.20,
            close_reason="TP",
            score=71.2,
        )
        assert "71.2" in msg
        assert "Score" in msg

    def test_does_not_contain_lot_size(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=28.6,
            pnl_usd=984.20,
            close_reason="TP",
            score=71.2,
            opened_at=self._opened,
            closed_at=self._now,
        )
        assert "lot" not in msg.lower()

    def test_does_not_contain_balance(self):
        msg = format_signal_close(
            symbol="XAUUSD",
            direction="BUY",
            pips=28.6,
            pnl_usd=984.20,
            close_reason="TP",
        )
        assert "balance" not in msg.lower()
        assert "equity" not in msg.lower()

    def test_positive_pnl_has_plus_sign(self):
        msg = format_signal_close(
            symbol="EURUSD",
            direction="BUY",
            pips=10.0,
            pnl_usd=100.0,
            close_reason="TP",
        )
        assert "+$100.00" in msg

    def test_negative_pnl_formatted_correctly(self):
        msg = format_signal_close(
            symbol="EURUSD",
            direction="BUY",
            pips=-10.0,
            pnl_usd=-100.0,
            close_reason="SL",
        )
        # Should contain the dollar amount
        assert "100.00" in msg
        # Negative pnl: pnl_sign should be "" (empty), so "+$" must NOT appear on result line
        result_line = next(
            (line for line in msg.splitlines() if "Result" in line), ""
        )
        assert "+$" not in result_line
        # And it must NOT show as a loss with a plus sign prefix
        assert result_line.count("+") <= 1  # at most the pip sign "+" for positive pips


# ── 3. send_signal_notification — failure is swallowed silently ───────────────

class TestSendSignalNotificationFailure:
    def test_telegram_exception_does_not_raise(self):
        """If the Telegram API throws, send_signal_notification must NOT propagate."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=RuntimeError("Network error"))

        def _cfg(key, default=None):
            if key == "telegram_signals.enabled":
                return True
            if key == "telegram_signals.channel_id":
                return "-100123456"
            return default

        with patch("src.telegram.signal_channel.get", side_effect=_cfg), \
             patch("src.telegram.client._init_telegram"), \
             patch("src.telegram.client._bot", mock_bot), \
             patch("src.telegram.client._enabled", True):
            # Must NOT raise
            _run(send_signal_notification("test message"))

    def test_network_error_is_logged_not_raised(self):
        """A warning is logged (not raised) on send failure."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("timeout"))

        def _cfg(key, default=None):
            if key == "telegram_signals.enabled":
                return True
            if key == "telegram_signals.channel_id":
                return "-100123456"
            return default

        with patch("src.telegram.signal_channel.get", side_effect=_cfg), \
             patch("src.telegram.client._init_telegram"), \
             patch("src.telegram.client._bot", mock_bot), \
             patch("src.telegram.client._enabled", True), \
             patch("src.telegram.signal_channel.log") as mock_log:
            _run(send_signal_notification("test message"))
            mock_log.warning.assert_called()


# ── 4. When enabled=false, no send is attempted ───────────────────────────────

class TestSignalDisabledByConfig:
    def test_disabled_config_skips_send(self):
        """When telegram_signals.enabled=false, bot.send_message is never called."""
        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock()

        with patch("src.telegram.signal_channel.get", return_value=False), \
             patch("src.telegram.client._bot", mock_bot), \
             patch("src.telegram.client._enabled", True):
            _run(send_signal_notification("this should not be sent"))

        mock_bot.send_message.assert_not_called()

    def test_disabled_config_returns_immediately(self):
        """Returns without touching the client module when disabled."""
        init_called = []

        with patch("src.telegram.signal_channel.get", return_value=False), \
             patch("src.telegram.client._init_telegram",
                   side_effect=lambda: init_called.append(1)):
            _run(send_signal_notification("test"))

        # _init_telegram (in client) should never be invoked when the feature is disabled
        assert init_called == [], "_init_telegram should not be called when disabled"


# ── 5. Private notification unaffected when signal channel fails ──────────────

class TestPrivateNotificationUnaffectedBySignalFailure:
    """
    Simulate the call pattern from position_monitor._handle_closed_position:
    _notify_closed (private) fires first, then _notify_signal_closed (public).
    A failure in the signal channel must NOT propagate back to the caller,
    and the private notification must already have completed successfully.
    """

    def test_private_notify_completes_before_signal_attempt(self):
        execution_order: list[str] = []

        async def fake_private_notify():
            execution_order.append("private")

        import src.telegram.signal_channel as sc

        def _cfg(key, default=None):
            if key == "telegram_signals.enabled":
                return True
            if key == "telegram_signals.channel_id":
                return "-100123456"
            return default

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=RuntimeError("channel failed"))

        async def _simulate():
            await fake_private_notify()              # Step 1: private (always first)
            with patch("src.telegram.signal_channel.get", side_effect=_cfg), \
                 patch("src.telegram.client._init_telegram"), \
                 patch("src.telegram.client._bot", mock_bot), \
                 patch("src.telegram.client._enabled", True):
                await send_signal_notification("test signal")  # Step 2: public (may fail)

        _run(_simulate())

        # Private notification ran first and completed successfully
        assert execution_order[0] == "private"

    def test_signal_failure_does_not_reraise(self):
        """Even with a broken Telegram bot, send_signal_notification never raises."""
        import src.telegram.signal_channel as sc

        def _cfg(key, default=None):
            if key == "telegram_signals.enabled":
                return True
            if key == "telegram_signals.channel_id":
                return "-100xyz"
            return default

        mock_bot = MagicMock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("boom"))

        with patch("src.telegram.signal_channel.get", side_effect=_cfg), \
             patch("src.telegram.client._init_telegram"), \
             patch("src.telegram.client._bot", mock_bot), \
             patch("src.telegram.client._enabled", True):
            try:
                _run(send_signal_notification("test"))
            except Exception as e:
                pytest.fail(f"send_signal_notification raised unexpectedly: {e}")
