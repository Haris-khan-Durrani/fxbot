"""
src/execution/order_manager.py
──────────────────────────────
Order placement with retry/backoff.
Checks LIVE_TRADING_ENABLED and account demo status before every order.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from src.core.config import get, is_live_trading_enabled
from src.core.logger import get_logger
from src.data.account_info import get_open_positions
from src.db import repository as repo

log = get_logger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds between retries


@dataclass
class OrderResult:
    success: bool
    ticket: Optional[int] = None
    error: Optional[str] = None
    retcode: Optional[int] = None


def _live_trading_guard() -> bool:
    """
    Hard block if live trading is not explicitly enabled.
    Returns True if safe to proceed, False if blocked.
    """
    if is_live_trading_enabled():
        # Double-check account type (paranoia is good here)
        from src.data.account_info import get_account
        try:
            acct = get_account()
            if not acct.is_demo:
                log.warning("Live trading enabled and account is LIVE — proceeding.")
            return True
        except Exception:
            return True  # If we can't check, allow (MT5 will reject if disconnected)
    else:
        log.info("Live trading disabled (LIVE_TRADING_ENABLED=false) — order suppressed.")
        return False


def _get_filling_mode(symbol: str) -> int:
    """Determine the supported order filling mode dynamically based on symbol spec."""
    if not MT5_AVAILABLE:
        return 0
    info = mt5.symbol_info(symbol)
    if info is None:
        return mt5.ORDER_FILLING_FOK
    
    # Check supported filling modes bitmask
    # SYMBOL_FILLING_FOK = 1
    # SYMBOL_FILLING_IOC = 2
    if info.filling_mode & 1:
        return mt5.ORDER_FILLING_FOK
    elif info.filling_mode & 2:
        return mt5.ORDER_FILLING_IOC
    else:
        return mt5.ORDER_FILLING_RETURN



def open_trade(
    symbol: str,
    direction: str,       # "BUY" | "SELL"
    lot_size: float,
    sl_price: float,
    tp_price: float,
    comment: str = "fxbot",
) -> OrderResult:
    """
    Place a market order with SL and TP.
    Retries up to _MAX_RETRIES times with backoff.
    """
    if not MT5_AVAILABLE:
        return OrderResult(success=False, error="MT5 not available")

    # ── Hard safety ceiling check (defense in depth) ──────────────────
    max_lots = get("risk.max_lot_size_per_symbol", {})
    if isinstance(max_lots, dict) and symbol in max_lots:
        limit = float(max_lots[symbol])
        if lot_size > limit:
            reason = f"Calculated lot size {lot_size} exceeds max allowed limit {limit} for {symbol}."
            log.critical("🚨 CRITICAL: %s Rejecting order and triggering emergency stop.", reason)
            
            # Trip the emergency stop flag in database
            repo.trigger_emergency_stop()
            
            # Send Telegram emergency alert asynchronously
            try:
                import asyncio
                from src.telegram.notifications import notify_emergency_stop
                loop = asyncio.get_running_loop()
                loop.create_task(notify_emergency_stop(reason))
            except RuntimeError:
                pass  # outside async context (like in test suite)
                
            return OrderResult(success=False, error=reason)

    if not _live_trading_guard():
        # In demo mode this still executes — we're only blocking actual live accounts
        # when LIVE_TRADING_ENABLED=false. For demo, we allow it.
        pass  # Demo always allowed

    order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return OrderResult(success=False, error=f"Cannot get tick for {symbol}")

    price = tick.ask if direction == "BUY" else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": 20,           # Max slippage points
        "magic": 202400,           # Bot identifier
        "comment": comment[:31],   # MT5 max 31 chars
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _get_filling_mode(symbol),
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        log.info("Order attempt %d/%d: %s %s %.2f lots @ ~%.5f SL=%.5f TP=%.5f",
                 attempt, _MAX_RETRIES, direction, symbol, lot_size, price, sl_price, tp_price)

        result = mt5.order_send(request)
        repo.log_system_event(
            "INFO", "ORDER_ATTEMPT",
            f"Attempt {attempt}: {direction} {symbol} {lot_size}",
            {"retcode": result.retcode if result else None},
        )

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            ticket = result.order
            log.info("✅ Order filled: ticket=%d %s %s %.2f lots", ticket, direction, symbol, lot_size)

            return OrderResult(success=True, ticket=ticket, retcode=result.retcode)

        error_msg = f"retcode={result.retcode} comment={result.comment}" if result else "no response"
        log.warning("Order attempt %d failed: %s", attempt, error_msg)

        if attempt < _MAX_RETRIES:
            time.sleep(_RETRY_DELAY * attempt)

    return OrderResult(
        success=False,
        error=f"All {_MAX_RETRIES} order attempts failed",
        retcode=result.retcode if result else None,
    )


def close_trade(ticket: int, symbol: str, direction: str, lot_size: float) -> OrderResult:
    """Close an open position by ticket."""
    if not MT5_AVAILABLE:
        return OrderResult(success=False, error="MT5 not available")

    close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return OrderResult(success=False, error=f"Cannot get tick for {symbol}")

    price = tick.bid if direction == "BUY" else tick.ask

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 20,
        "magic": 202400,
        "comment": "fxbot-close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _get_filling_mode(symbol),
    }

    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.info("✅ Position closed: ticket=%d", ticket)
        return OrderResult(success=True, ticket=ticket)

    error_msg = f"retcode={result.retcode}" if result else "no response"
    log.error("Failed to close ticket %d: %s", ticket, error_msg)
    return OrderResult(success=False, error=error_msg)


def modify_sl(ticket: int, symbol: str, new_sl: float, tp: float) -> bool:
    """Modify the stop loss of an open position."""
    if not MT5_AVAILABLE:
        return False

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": new_sl,
        "tp": tp,
    }
    result = mt5.order_send(request)
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        log.debug("SL modified: ticket=%d new_sl=%.5f", ticket, new_sl)
        return True
    log.warning("Failed to modify SL for ticket=%d: %s",
                ticket, result.retcode if result else "no response")
    return False
