"""
src/execution/position_monitor.py
──────────────────────────────────
Continuous loop checking open positions for trailing/break-even triggers.
Called on every main loop iteration when there are open trades.
"""
from __future__ import annotations

from src.core.logger import get_logger
from src.data.account_info import OpenPosition, get_open_positions
from src.data.candles import get_candles
from src.data.symbol_info import get_symbol_spec
from src.db import repository as repo
from src.execution.order_manager import close_trade, modify_sl
from src.risk.position_sizing import calc_sl_pips_from_atr
from src.risk.trailing import (
    calc_break_even_level,
    calc_trailing_sl,
    should_trigger_break_even,
    should_trigger_trailing,
)
from src.strategy.session_filter import SessionResult

log = get_logger(__name__)


def monitor_positions(session: SessionResult) -> None:
    """
    Check all open positions and apply:
      1. Break-even (move SL to entry once profit ≥ 1× risk)
      2. Trailing stop (adjust SL as price moves in profit)

    Also detects positions closed by SL/TP in MT5 and records them in DB.
    """
    db_trades = repo.get_open_trades()
    if not db_trades:
        return

    try:
        mt5_positions = get_open_positions()
    except Exception as e:
        log.error("Position monitor: cannot fetch MT5 positions: %s", e)
        return

    mt5_by_ticket = {p.ticket: p for p in mt5_positions}

    for trade in db_trades:
        mt5_pos = mt5_by_ticket.get(trade.mt5_ticket)

        if mt5_pos is None:
            # Position was closed (SL/TP hit, or manual close)
            _handle_closed_position(trade, session)
            continue

        # ── Break-even check ──────────────────────────────────────────
        try:
            spec = get_symbol_spec(trade.symbol)
        except Exception:
            continue

        if should_trigger_break_even(mt5_pos, trade, spec):
            be_level = calc_break_even_level(trade, spec)
            success = modify_sl(trade.mt5_ticket, trade.symbol, be_level, trade.tp_price or 0)
            if success:
                repo.update_trade_sl(trade.mt5_ticket, be_level)
                repo.mark_break_even(trade.mt5_ticket)
                log.info("🛡️ Break-even set: ticket=%d %s @ %.5f",
                         trade.mt5_ticket, trade.symbol, be_level)

        # ── Trailing stop check ───────────────────────────────────────
        if should_trigger_trailing(mt5_pos, trade):
            repo.mark_trailing(trade.mt5_ticket)
            try:
                df_m15 = get_candles(trade.symbol, "M15", count=30)
                atr_val = float(calc_sl_pips_from_atr(df_m15,
                                                       multiplier=1.0))  # Raw ATR
            except Exception:
                continue

            current_sl = trade.sl_price or mt5_pos.sl
            new_sl = calc_trailing_sl(mt5_pos, current_sl, spec, atr_val)

            if new_sl != current_sl:
                success = modify_sl(trade.mt5_ticket, trade.symbol, new_sl, trade.tp_price or 0)
                if success:
                    repo.update_trade_sl(trade.mt5_ticket, new_sl)
                    log.info("📈 Trailing SL: ticket=%d moved to %.5f",
                             trade.mt5_ticket, new_sl)


def _handle_closed_position(trade, session: SessionResult) -> None:
    """Handle a DB trade whose MT5 position no longer exists."""
    # Try to get the historical deal from MT5
    close_price, actual_pnl, deal_reason = _get_close_details_from_history(trade.mt5_ticket)
    
    if close_price is None:
        close_price = trade.open_price
        pnl = 0.0
        pips = 0.0
        reason = "UNKNOWN"
    else:
        try:
            spec = get_symbol_spec(trade.symbol)
        except Exception:
            spec = None

        if spec:
            pip_size = spec.point * 10
            diff = (close_price - trade.open_price) if trade.direction == "BUY" else (trade.open_price - close_price)
            pips = diff / pip_size
        else:
            # Fallback
            if trade.direction == "BUY":
                pips = (close_price - trade.open_price) / (0.0001 if "USD" in trade.symbol else 0.01)
            else:
                pips = (trade.open_price - close_price) / (0.0001 if "USD" in trade.symbol else 0.01)
        
        if actual_pnl is not None:
            pnl = actual_pnl
        else:
            pnl = _estimate_pnl(trade, close_price, spec)
            
        reason = deal_reason or _infer_close_reason(close_price, trade, spec)

    closed_hist = repo.close_trade(
        mt5_ticket=trade.mt5_ticket,
        close_price=close_price,
        pips=round(pips, 1),
        pnl_usd=round(pnl, 2),
        close_reason=reason,
        session_label=session.label.value,
    )
    
    if closed_hist:
        repo.record_trade_result(pnl)

        log.info("📋 Position closed recorded: ticket=%d reason=%s pnl=%.2f",
                 trade.mt5_ticket, reason, pnl)

        # ── AI Option B: Post-Trade Review ──────────────────────
        _run_ai_post_trade_review(trade, close_price, round(pnl, 2), round(pips, 1), reason)

        # Send Telegram notification (non-blocking)
        _notify_closed(trade, pnl, pips, reason)

        # ── Signal channel broadcast (public, fire-and-forget) ────────────
        # Always AFTER private notification and AFTER DB write confirmed.
        # Failure is silently swallowed inside send_signal_notification.
        _notify_signal_closed(trade, round(pips, 1), round(pnl, 2), reason, closed_hist)


def _get_close_details_from_history(ticket: int) -> tuple[float | None, float | None, str | None]:
    """Pull close price, actual P&L, and close reason from MT5 deal history."""
    try:
        import MetaTrader5 as mt5
        deals = mt5.history_deals_get(position=ticket)
        if deals:
            # Find the closing deal (entry_type == DEAL_ENTRY_OUT)
            close_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
            if close_deals:
                close_deal = close_deals[-1]
                pnl = close_deal.profit + close_deal.swap + close_deal.commission
                
                # Map MetaTrader5 reason codes if possible
                deal_reason = None
                if hasattr(mt5, "DEAL_REASON_SL") and close_deal.reason == mt5.DEAL_REASON_SL:
                    deal_reason = "SL"
                elif hasattr(mt5, "DEAL_REASON_TP") and close_deal.reason == mt5.DEAL_REASON_TP:
                    deal_reason = "TP"
                elif hasattr(mt5, "DEAL_REASON_CLIENT") and close_deal.reason == mt5.DEAL_REASON_CLIENT:
                    deal_reason = "MANUAL"
                    
                return close_deal.price, pnl, deal_reason
    except Exception:
        pass
    return None, None, None


def _estimate_pnl(trade, close_price: float, spec=None) -> float:
    """Rough P&L estimate from price diff × lot size × contract size."""
    try:
        if spec is None:
            spec = get_symbol_spec(trade.symbol)
        if trade.direction == "BUY":
            diff = close_price - trade.open_price
        else:
            diff = trade.open_price - close_price
        # pips from diff
        pip_size = spec.point * 10
        pips = diff / pip_size
        return pips * spec.pip_value_per_lot * trade.lot_size
    except Exception:
        return 0.0


def _infer_close_reason(close_price: float, trade, spec=None) -> str:
    # 5 pips threshold: 50 points (point * 50) or fallback to 0.0005 for forex, 0.50 for gold
    threshold = 0.0005
    if spec:
        threshold = spec.point * 50
    elif "XAUUSD" in trade.symbol.upper():
        threshold = 0.50

    if trade.tp_price and abs(close_price - trade.tp_price) < threshold:
        return "TP"
    if trade.sl_price and abs(close_price - trade.sl_price) < threshold:
        return "SL"
    return "MANUAL"


def _notify_closed(trade, pnl: float, pips: float, reason: str) -> None:
    try:
        from src.telegram.notifications import notify_trade_closed
        import asyncio
        asyncio.create_task(notify_trade_closed(trade, pnl, pips, reason))
    except Exception:
        pass  # Never crash the monitor loop due to Telegram


def _notify_signal_closed(trade, pips: float, pnl_usd: float, reason: str, closed_hist) -> None:
    """
    Broadcast the closed-trade result to the public signal channel.

    Must always be called AFTER _notify_closed (private) and AFTER DB write.
    Failure is silently swallowed — never blocks the monitor loop.
    """
    try:
        from src.core.config import get
        if not get("telegram_signals.enabled", False):
            return

        import asyncio
        from datetime import datetime, timezone
        from src.telegram.signal_channel import format_signal_close, send_signal_notification

        # Resolve open/close timestamps from DB record if available
        opened_at: datetime | None = None
        closed_at: datetime | None = None
        if closed_hist is not None:
            opened_at = getattr(closed_hist, "opened_at", None) or getattr(trade, "opened_at", None)
            closed_at = getattr(closed_hist, "closed_at", None)
        if closed_at is None:
            closed_at = datetime.now(timezone.utc)

        # Normalise timestamps to UTC-aware if naive
        if opened_at is not None and opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=timezone.utc)
        if closed_at is not None and closed_at.tzinfo is None:
            closed_at = closed_at.replace(tzinfo=timezone.utc)

        score = getattr(trade, "signal_score", None)

        msg = format_signal_close(
            symbol=trade.symbol,
            direction=trade.direction,
            pips=pips,
            pnl_usd=pnl_usd,
            close_reason=reason,
            score=score,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        asyncio.create_task(send_signal_notification(msg))
    except Exception as e:
        log.warning("Signal channel close broadcast skipped (non-fatal): %s", e)


def _run_ai_post_trade_review(trade, close_price: float, pnl: float, pips: float, reason: str) -> None:
    """
    Launches AI post-mortem review as a background async task.
    Never blocks the monitor loop.
    """
    try:
        from src.ai.client import is_ai_enabled, analyze_post_trade
        if not is_ai_enabled():
            return

        trade_data = {
            "symbol": trade.symbol,
            "direction": trade.direction,
            "open_price": trade.open_price,
            "close_price": close_price,
            "pnl_usd": pnl,
            "pips": pips,
            "close_reason": reason,
            "signal_score": getattr(trade, "signal_score", None),
            "lot_size": trade.lot_size,
        }

        import asyncio
        async def _run():
            try:
                analysis = await analyze_post_trade(trade_data)
                # Update the history record with the AI analysis
                from src.db import repository as _repo
                from sqlalchemy import update
                from src.db.models import TradeHistory, get_session
                with get_session() as s:
                    s.execute(
                        update(TradeHistory)
                        .where(TradeHistory.mt5_ticket == trade.mt5_ticket)
                        .values(ai_analysis=analysis)
                    )
                    s.commit()
                log.info("AI post-trade review saved for ticket=%d", trade.mt5_ticket)
            except Exception as e:
                log.warning("AI post-trade review async task failed: %s", e)

        asyncio.create_task(_run())
    except Exception as e:
        log.warning("AI post-trade review skipped: %s", e)
