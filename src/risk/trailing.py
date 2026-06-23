"""
src/risk/trailing.py
────────────────────
Break-even and trailing stop logic.
Called by the position monitor loop on each tick.
"""
from __future__ import annotations

from src.core.config import get
from src.core.logger import get_logger
from src.data.account_info import OpenPosition
from src.db import repository as repo

log = get_logger(__name__)


def _pips_to_price(pips: float, symbol: str, spec) -> float:
    """Convert pip distance to price distance using symbol spec."""
    return pips * spec.point * 10


def calc_break_even_level(trade_db, spec) -> float:
    """Return the break-even SL price (= entry price ± small buffer)."""
    buffer_pips = 1.0
    buffer = _pips_to_price(buffer_pips, trade_db.symbol, spec)
    if trade_db.direction == "BUY":
        return trade_db.open_price + buffer
    else:
        return trade_db.open_price - buffer


def should_trigger_break_even(
    position: OpenPosition,
    trade_db,
    spec,
) -> bool:
    """
    Returns True if the position has moved enough profit to justify break-even.
    Threshold = entry_risk × be_trigger_rr (from config).
    """
    if trade_db.break_even_triggered:
        return False

    trigger_rr = get("risk.break_even.trigger_rr", 1.0)
    sl_distance = abs(trade_db.open_price - trade_db.sl_price) if trade_db.sl_price else 0
    if sl_distance <= 0:
        return False

    be_trigger_price = sl_distance * trigger_rr

    if position.direction == "BUY":
        profit_pips = position.current_price - trade_db.open_price
    else:
        profit_pips = trade_db.open_price - position.current_price

    return round(profit_pips, 7) >= round(be_trigger_price, 7)


def calc_trailing_sl(
    position: OpenPosition,
    current_sl: float,
    spec,
    atr_value: float,
) -> float:
    """
    Calculate new trailing SL price.
    Trail by `trail_atr_multiplier` × ATR from current price.
    Returns new SL only if it improves (moves in profitable direction).
    """
    multiplier = get("risk.trailing_stop.trail_atr_multiplier", 1.0)
    trail_distance = atr_value * multiplier

    if position.direction == "BUY":
        new_sl = position.current_price - trail_distance
        return new_sl if new_sl > current_sl else current_sl
    else:
        new_sl = position.current_price + trail_distance
        return new_sl if new_sl < current_sl else current_sl


def should_trigger_trailing(
    position: OpenPosition,
    trade_db,
) -> bool:
    """Returns True once position reaches the trailing trigger threshold."""
    if not trade_db.sl_price:
        return False

    trigger_rr = get("risk.trailing_stop.trigger_rr", 1.5)
    sl_distance = abs(trade_db.open_price - trade_db.sl_price)
    if sl_distance <= 0:
        return False

    trigger_distance = sl_distance * trigger_rr

    if position.direction == "BUY":
        profit = position.current_price - trade_db.open_price
    else:
        profit = trade_db.open_price - position.current_price

    return round(profit, 7) >= round(trigger_distance, 7)
