"""
src/data/account_info.py
────────────────────────
Live account info: balance, equity, margin, open positions.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.core.logger import get_logger
from src.data.mt5_connection import MT5_AVAILABLE, ensure_connected

log = get_logger(__name__)

if MT5_AVAILABLE:
    import MetaTrader5 as mt5


@dataclass
class AccountSnapshot:
    login: int
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: Optional[float]   # None if no open positions
    currency: str
    is_demo: bool


@dataclass
class OpenPosition:
    ticket: int
    symbol: str
    direction: str      # BUY | SELL
    volume: float       # Lot size
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float       # Floating P&L in account currency
    swap: float
    comment: str


def get_account() -> AccountSnapshot:
    if not MT5_AVAILABLE or not ensure_connected():
        raise RuntimeError("MT5 not connected.")
    info = mt5.account_info()
    if info is None:
        raise RuntimeError("MT5 account_info() returned None.")
    return AccountSnapshot(
        login=info.login,
        balance=info.balance,
        equity=info.equity,
        margin=info.margin,
        free_margin=info.margin_free,
        margin_level=info.margin_level if info.margin_level else None,
        currency=info.currency,
        is_demo=(info.trade_mode == 0),
    )


def get_open_positions(symbol: Optional[str] = None) -> list[OpenPosition]:
    """Get all open MT5 positions, optionally filtered by symbol."""
    if not MT5_AVAILABLE or not ensure_connected():
        return []
    positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
    if positions is None:
        return []
    result = []
    for p in positions:
        result.append(OpenPosition(
            ticket=p.ticket,
            symbol=p.symbol,
            direction="BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
            volume=p.volume,
            open_price=p.price_open,
            current_price=p.price_current,
            sl=p.sl,
            tp=p.tp,
            profit=p.profit,
            swap=p.swap,
            comment=p.comment or "",
        ))
    return result


def get_server_time() -> Optional[float]:
    """
    Returns broker server time as a Unix timestamp (UTC).
    Used by session_filter.py to derive session windows from server time.
    """
    if not MT5_AVAILABLE or not ensure_connected():
        return None
    # Use any liquid symbol tick to get server time
    tick = mt5.symbol_info_tick("EURUSD")
    if tick:
        return tick.time  # Unix timestamp
    return None
