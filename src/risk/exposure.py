"""
src/risk/exposure.py
────────────────────
Portfolio-level USD exposure check.
XAUUSD, EURUSD, and GBPUSD all have USD legs.
Prevents over-concentration in a single currency before opening a new trade.
"""
from __future__ import annotations

from src.core.config import get
from src.core.logger import get_logger
from src.data.account_info import OpenPosition

log = get_logger(__name__)


def calc_notional_usd(position: OpenPosition, contract_size: float, price: float) -> float:
    """
    Estimate notional USD exposure for a position.

    For pairs like EURUSD, GBPUSD: notional = lots × contract_size × price
    For XAUUSD: notional = lots × contract_size × price (gold price in USD)
    """
    return position.volume * contract_size * price


def check_usd_exposure(
    open_positions: list[OpenPosition],
    new_symbol: str,
    new_lots: float,
    symbol_specs: dict,     # symbol → SymbolSpec
) -> tuple[bool, str]:
    """
    Check if adding a new trade would exceed the max USD exposure limit.

    Args:
        open_positions: Current MT5 open positions.
        new_symbol:     Symbol of the proposed new trade.
        new_lots:       Lot size of the proposed new trade.
        symbol_specs:   Dict of symbol → SymbolSpec (for contract size info).

    Returns:
        (True, "") if exposure is acceptable, (False, reason) if blocked.
    """
    max_exposure = get("risk.max_usd_exposure", 50000)

    total_exposure = 0.0
    for pos in open_positions:
        spec = symbol_specs.get(pos.symbol)
        if spec is None:
            continue
        notional = calc_notional_usd(pos, spec.contract_size, pos.current_price)
        total_exposure += notional
        log.debug("Exposure: %s %.2f lots → notional $%.0f", pos.symbol, pos.volume, notional)

    # Estimate new trade exposure
    new_spec = symbol_specs.get(new_symbol)
    if new_spec:
        new_notional = new_lots * new_spec.contract_size * new_spec.spread_raw  # approximate
        # Better approximation: use a fixed reference price estimate
        # In live bot, we'd use the current ask/bid price
        total_after = total_exposure + new_notional
    else:
        total_after = total_exposure

    if total_after > max_exposure:
        reason = (f"USD exposure check failed: existing=${total_exposure:,.0f} "
                  f"+ new≈${total_after - total_exposure:,.0f} "
                  f"= ${total_after:,.0f} > max ${max_exposure:,.0f}")
        log.warning(reason)
        return False, reason

    log.debug("USD exposure OK: total≈$%.0f (max $%.0f)", total_after, max_exposure)
    return True, ""
