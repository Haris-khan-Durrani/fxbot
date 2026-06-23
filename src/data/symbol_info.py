"""
src/data/symbol_info.py
───────────────────────
Per-symbol specs fetched live from MT5 — never hardcoded.
XAUUSD has very different pip values, lot steps, etc. from EURUSD/GBPUSD.
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
class SymbolSpec:
    symbol: str
    pip_value_per_lot: float      # USD per pip per standard lot
    lot_step: float               # Minimum lot increment
    min_lot: float
    max_lot: float
    contract_size: float          # Units per standard lot (e.g. 100000 for EURUSD, 100 for XAUUSD)
    point: float                  # 1 point = smallest price movement
    digits: int                   # Decimal places
    spread_raw: float             # Current spread in points
    spread_pips: float            # Current spread in pips

    @property
    def pips_to_price(self) -> float:
        """Convert 1 pip to price movement (10 points for most pairs)."""
        # For most FX: 1 pip = 10 points. For XAUUSD: 1 pip = 10 points (0.01 USD)
        return self.point * 10


_OFFLINE_SPECS = {
    "EURUSD": SymbolSpec(
        symbol="EURUSD", pip_value_per_lot=10.0,
        lot_step=0.01, min_lot=0.01, max_lot=500.0,
        contract_size=100000.0, point=0.00001, digits=5,
        spread_raw=2.0, spread_pips=0.2
    ),
    "GBPUSD": SymbolSpec(
        symbol="GBPUSD", pip_value_per_lot=10.0,
        lot_step=0.01, min_lot=0.01, max_lot=500.0,
        contract_size=100000.0, point=0.00001, digits=5,
        spread_raw=2.0, spread_pips=0.2
    ),
    "NZDUSD": SymbolSpec(
        symbol="NZDUSD", pip_value_per_lot=10.0,
        lot_step=0.01, min_lot=0.01, max_lot=500.0,
        contract_size=100000.0, point=0.00001, digits=5,
        spread_raw=2.0, spread_pips=0.2
    ),
    "XAUUSD": SymbolSpec(
        symbol="XAUUSD", pip_value_per_lot=10.0,
        lot_step=0.01, min_lot=0.01, max_lot=100.0,
        contract_size=100.0, point=0.01, digits=2,
        spread_raw=30.0, spread_pips=3.0
    ),
}


def get_symbol_spec(symbol: str) -> SymbolSpec:
    """
    Fetch live symbol specifications from MT5.
    If MT5 is unavailable or disconnected, falls back to offline cached specifications.
    """
    if not MT5_AVAILABLE or not ensure_connected():
        if symbol in _OFFLINE_SPECS:
            log.warning("MT5 not connected. Using offline spec fallback for %s", symbol)
            return _OFFLINE_SPECS[symbol]
        raise RuntimeError(f"MT5 not connected and no offline cached spec for {symbol!r}")

    info = mt5.symbol_info(symbol)
    if info is None:
        if symbol in _OFFLINE_SPECS:
            log.warning("Symbol %s not found in MT5. Using offline spec fallback", symbol)
            return _OFFLINE_SPECS[symbol]
        raise ValueError(f"Symbol {symbol!r} not found in MT5 and no offline cached spec.")

    # Ensure symbol is visible/selected in market watch
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            if symbol in _OFFLINE_SPECS:
                log.warning("Could not select symbol %s. Using offline spec fallback", symbol)
                return _OFFLINE_SPECS[symbol]
            raise RuntimeError(f"Could not select symbol {symbol!r} in market watch.")
        info = mt5.symbol_info(symbol)

    # 1 pip = 10 points standard
    pips_per_point = 10
    pip_size = info.point * pips_per_point

    # Calculate pip value dynamically using order_calc_profit to prevent broker CFD scaling issues
    open_price = info.ask if info.ask > 0 else (info.bid if info.bid > 0 else 1.0)
    calc_val = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, symbol, 1.0, open_price, open_price + pip_size)
    if calc_val is not None:
        pip_value = abs(calc_val)
    else:
        # Fallback to tick value if order_calc_profit fails
        pip_value = info.trade_tick_value * pips_per_point
        log.warning("order_calc_profit failed for %s, using tick value fallback: %.4f", symbol, pip_value)

    spread_pips = info.spread / pips_per_point

    return SymbolSpec(
        symbol=symbol,
        pip_value_per_lot=pip_value,
        lot_step=info.volume_step,
        min_lot=info.volume_min,
        max_lot=info.volume_max,
        contract_size=info.trade_contract_size,
        point=info.point,
        digits=info.digits,
        spread_raw=info.spread,
        spread_pips=spread_pips,
    )


def get_current_spread_pips(symbol: str) -> float:
    """Get the current live spread in pips (quick check, no full spec fetch)."""
    if not MT5_AVAILABLE or not ensure_connected():
        return 0.0
    info = mt5.symbol_info(symbol)
    if info is None:
        return 0.0
    pips_per_point = 10
    return info.spread / pips_per_point
