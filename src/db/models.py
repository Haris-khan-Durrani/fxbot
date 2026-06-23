"""
src/db/models.py
────────────────
SQLAlchemy ORM models for all 7 MySQL tables.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import mysql_url


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────
# Table: settings (key-value store for runtime flags)
# ─────────────────────────────────────────────────────────────────
class Settings(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────
# Table: signals (every scored signal, even those below threshold)
# ─────────────────────────────────────────────────────────────────
class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)        # BUY | SELL
    score = Column(Float, nullable=False)
    score_trend = Column(Float, nullable=False, default=0)
    score_structure = Column(Float, nullable=False, default=0)
    score_liquidity = Column(Float, nullable=False, default=0)
    score_momentum = Column(Float, nullable=False, default=0)
    score_session = Column(Float, nullable=False, default=0)
    passed_threshold = Column(Boolean, nullable=False, default=False)
    reason_skip = Column(String(200), nullable=True)      # Why it was skipped
    signal_price = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    # ── AI Fields ──────────────────────────────────────────────────────
    ai_sentiment = Column(String(20), nullable=True)       # BULLISH | BEARISH | NEUTRAL
    ai_score_adjustment = Column(Float, nullable=True)     # -20 to +20
    ai_summary = Column(Text, nullable=True)               # One-liner from Gemini


# ─────────────────────────────────────────────────────────────────
# Table: trades (currently open positions)
# ─────────────────────────────────────────────────────────────────
class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mt5_ticket = Column(BigInteger, unique=True, nullable=False, index=True)
    symbol = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)       # BUY | SELL
    lot_size = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    signal_score = Column(Float, nullable=True)
    opened_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    break_even_triggered = Column(Boolean, default=False)
    trailing_triggered = Column(Boolean, default=False)
    status = Column(String(20), nullable=False, default="OPEN")  # OPEN | CLOSING


# ─────────────────────────────────────────────────────────────────
# Table: trade_history (completed trades)
# ─────────────────────────────────────────────────────────────────
class TradeHistory(Base):
    __tablename__ = "trade_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mt5_ticket = Column(BigInteger, nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    lot_size = Column(Float, nullable=False)
    open_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    pips = Column(Float, nullable=False)
    pnl_usd = Column(Float, nullable=False)
    signal_score = Column(Float, nullable=True)
    opened_at = Column(DateTime, nullable=False)
    closed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    close_reason = Column(String(50), nullable=True)     # TP | SL | MANUAL | TRAILING
    session = Column(String(20), nullable=True)          # LONDON | NEW_YORK | OVERLAP | OFF
    # ── AI Fields ──────────────────────────────────────────────────────
    ai_analysis = Column(Text, nullable=True)             # Post-mortem written by Gemini


# ─────────────────────────────────────────────────────────────────
# Table: daily_stats (one row per calendar day)
# ─────────────────────────────────────────────────────────────────
class DailyStat(Base):
    __tablename__ = "daily_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String(10), unique=True, nullable=False, index=True)  # YYYY-MM-DD
    trades_opened = Column(Integer, default=0)
    trades_closed = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    pnl_usd = Column(Float, default=0.0)
    max_drawdown_pct = Column(Float, default=0.0)
    starting_balance = Column(Float, nullable=True)
    ending_balance = Column(Float, nullable=True)
    emergency_stop_triggered = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────
# Table: performance_metrics (computed daily/weekly aggregates)
# ─────────────────────────────────────────────────────────────────
class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    period_type = Column(String(10), nullable=False)     # DAILY | WEEKLY | MONTHLY
    period_label = Column(String(20), nullable=False)    # e.g. "2024-W12" or "2024-03"
    symbol = Column(String(20), nullable=True)           # NULL = all pairs
    win_rate = Column(Float, nullable=True)
    profit_factor = Column(Float, nullable=True)
    total_trades = Column(Integer, nullable=True)
    total_pnl_usd = Column(Float, nullable=True)
    max_drawdown_pct = Column(Float, nullable=True)
    avg_rr = Column(Float, nullable=True)
    session_london_pnl = Column(Float, nullable=True)
    session_ny_pnl = Column(Float, nullable=True)
    computed_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────
# Table: system_logs (critical events: reconnects, emergency stops)
# ─────────────────────────────────────────────────────────────────
class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), nullable=False)           # INFO | WARNING | ERROR | CRITICAL
    event_type = Column(String(50), nullable=False)      # MT5_RECONNECT | EMERGENCY_STOP | etc.
    message = Column(Text, nullable=False)
    extra = Column(Text, nullable=True)                  # JSON string for structured extras
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# ─────────────────────────────────────────────────────────────────
# Engine + Session factory
# ─────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_engine():
    from src.core.config import get
    pool_size = get("database.pool_size", 5)
    pool_recycle = get("database.pool_recycle", 3600)
    return create_engine(
        mysql_url(),
        pool_size=pool_size,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        echo=False,
    )


def get_session() -> Session:
    """Return a new SQLAlchemy session. Caller is responsible for closing."""
    SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return SessionLocal()
