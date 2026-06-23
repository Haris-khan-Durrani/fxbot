"""
src/db/repository.py
────────────────────
Data access layer. All DB reads/writes go through here — no raw SQL elsewhere.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, date
from typing import Generator, Optional

from sqlalchemy.orm import Session

from src.core.logger import get_logger
from src.db.models import (
    DailyStat, PerformanceMetric, Settings, Signal,
    SystemLog, Trade, TradeHistory, get_session,
)

log = get_logger(__name__)


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations."""
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Settings ────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with session_scope() as s:
        row = s.query(Settings).filter_by(key=key).first()
        return row.value if row else default


def set_setting(key: str, value: str) -> None:
    with session_scope() as s:
        row = s.query(Settings).filter_by(key=key).first()
        if row:
            row.value = value
            row.updated_at = datetime.utcnow()
        else:
            s.add(Settings(key=key, value=value))


def is_emergency_stop() -> bool:
    return get_setting("emergency_stop", "false").lower() == "true"


def trigger_emergency_stop() -> None:
    set_setting("emergency_stop", "true")
    log_system_event("CRITICAL", "EMERGENCY_STOP", "Emergency stop triggered — all new orders blocked.")
    log.critical("🚨 EMERGENCY STOP TRIGGERED")


def reset_emergency_stop() -> None:
    set_setting("emergency_stop", "false")
    log_system_event("INFO", "EMERGENCY_STOP_RESET", "Emergency stop manually reset.")
    log.warning("Emergency stop reset — trading resumed.")


# ─── Signals ─────────────────────────────────────────────────────

def insert_signal(
    symbol: str, direction: str, score: float,
    score_trend: float, score_structure: float, score_liquidity: float,
    score_momentum: float, score_session: float,
    passed: bool, signal_price: float, reason_skip: Optional[str] = None,
    ai_sentiment: Optional[str] = None,
    ai_score_adjustment: Optional[float] = None,
    ai_summary: Optional[str] = None,
) -> Signal:
    with session_scope() as s:
        sig = Signal(
            symbol=symbol, direction=direction, score=score,
            score_trend=score_trend, score_structure=score_structure,
            score_liquidity=score_liquidity, score_momentum=score_momentum,
            score_session=score_session,
            passed_threshold=passed, signal_price=signal_price,
            reason_skip=reason_skip,
            ai_sentiment=ai_sentiment,
            ai_score_adjustment=ai_score_adjustment,
            ai_summary=ai_summary,
        )
        s.add(sig)
        s.flush()
        return sig


# ─── Trades ──────────────────────────────────────────────────────

def insert_trade(
    mt5_ticket: int, symbol: str, direction: str, lot_size: float,
    open_price: float, sl_price: Optional[float], tp_price: Optional[float],
    signal_score: Optional[float] = None,
) -> Trade:
    with session_scope() as s:
        trade = Trade(
            mt5_ticket=mt5_ticket, symbol=symbol, direction=direction,
            lot_size=lot_size, open_price=open_price,
            sl_price=sl_price, tp_price=tp_price,
            signal_score=signal_score,
            opened_at=datetime.utcnow(), status="OPEN",
        )
        s.add(trade)
        s.flush()
        log.info("Trade inserted: ticket=%d %s %s %.2f lots", mt5_ticket, symbol, direction, lot_size)
        return trade


def get_open_trades() -> list[Trade]:
    with session_scope() as s:
        trades = s.query(Trade).filter_by(status="OPEN").all()
        s.expunge_all()
        return trades


def get_trade_by_ticket(ticket: int) -> Optional[Trade]:
    with session_scope() as s:
        trade = s.query(Trade).filter_by(mt5_ticket=ticket).first()
        if trade:
            s.expunge(trade)
        return trade


def count_open_trades() -> int:
    with session_scope() as s:
        return s.query(Trade).filter_by(status="OPEN").count()


def close_trade(
    mt5_ticket: int, close_price: float, pips: float, pnl_usd: float,
    close_reason: str = "UNKNOWN", session_label: str = "UNKNOWN",
    ai_analysis: Optional[str] = None,
) -> Optional[TradeHistory]:
    with session_scope() as s:
        trade = s.query(Trade).filter_by(mt5_ticket=mt5_ticket).first()
        if not trade:
            log.warning("close_trade: ticket %d not found in trades table", mt5_ticket)
            return None

        history = TradeHistory(
            mt5_ticket=trade.mt5_ticket, symbol=trade.symbol,
            direction=trade.direction, lot_size=trade.lot_size,
            open_price=trade.open_price, close_price=close_price,
            sl_price=trade.sl_price, tp_price=trade.tp_price,
            pips=pips, pnl_usd=pnl_usd,
            signal_score=trade.signal_score,
            opened_at=trade.opened_at, closed_at=datetime.utcnow(),
            close_reason=close_reason, session=session_label,
            ai_analysis=ai_analysis,
        )
        s.add(history)
        s.delete(trade)
        s.flush()
        log.info("Trade closed: ticket=%d P&L=%.2f pips=%.1f reason=%s",
                 mt5_ticket, pnl_usd, pips, close_reason)
        return history


def update_trade_sl(mt5_ticket: int, new_sl: float) -> None:
    with session_scope() as s:
        trade = s.query(Trade).filter_by(mt5_ticket=mt5_ticket).first()
        if trade:
            trade.sl_price = new_sl
            log.debug("SL updated: ticket=%d new_sl=%.5f", mt5_ticket, new_sl)


def mark_break_even(mt5_ticket: int) -> None:
    with session_scope() as s:
        trade = s.query(Trade).filter_by(mt5_ticket=mt5_ticket).first()
        if trade:
            trade.break_even_triggered = True


def mark_trailing(mt5_ticket: int) -> None:
    with session_scope() as s:
        trade = s.query(Trade).filter_by(mt5_ticket=mt5_ticket).first()
        if trade:
            trade.trailing_triggered = True


# ─── Daily Stats ─────────────────────────────────────────────────

def get_or_create_daily_stat(date_str: Optional[str] = None) -> DailyStat:
    date_str = date_str or date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=date_str).first()
        if not stat:
            stat = DailyStat(date=date_str)
            s.add(stat)
            s.flush()
        s.expunge(stat)
        return stat


def increment_daily_trades(date_str: Optional[str] = None) -> None:
    date_str = date_str or date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=date_str).first()
        if not stat:
            stat = DailyStat(date=date_str)
            s.add(stat)
        stat.trades_opened = (stat.trades_opened or 0) + 1


def record_trade_result(pnl_usd: float, date_str: Optional[str] = None) -> None:
    date_str = date_str or date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=date_str).first()
        if not stat:
            stat = DailyStat(date=date_str)
            s.add(stat)
        stat.trades_closed = (stat.trades_closed or 0) + 1
        stat.pnl_usd = (stat.pnl_usd or 0.0) + pnl_usd
        if pnl_usd > 0:
            stat.wins = (stat.wins or 0) + 1
        else:
            stat.losses = (stat.losses or 0) + 1


def get_today_trade_count() -> int:
    date_str = date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=date_str).first()
        return stat.trades_opened if stat else 0


def get_today_pnl() -> float:
    date_str = date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=date_str).first()
        return stat.pnl_usd if stat else 0.0


# ─── System Logs ─────────────────────────────────────────────────

def log_system_event(
    level: str, event_type: str, message: str, extra: Optional[dict] = None
) -> None:
    try:
        with session_scope() as s:
            s.add(SystemLog(
                level=level, event_type=event_type, message=message,
                extra=json.dumps(extra) if extra else None,
            ))
    except Exception as exc:
        log.error("Failed to write system log to DB: %s", exc)


def clear_signals() -> None:
    """Delete all signals from the Signal table."""
    with session_scope() as s:
        deleted = s.query(Signal).delete()
    # log_system_event opens its own session_scope — must be called OUTSIDE ours
    # to avoid nested-transaction conflicts on MySQL
    log.info("Scanner signals cleared from database. (%d rows deleted)", deleted)
    log_system_event("INFO", "SCANNER_CLEAR", f"Scanner signals cleared manually. ({deleted} rows)")

