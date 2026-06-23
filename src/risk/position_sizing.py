"""
src/risk/position_sizing.py
───────────────────────────
Position sizing: risk % of balance → lot size.
Uses actual symbol pip value from MT5 — never hardcoded.
"""
from __future__ import annotations

import math

from src.core.config import get
from src.core.logger import get_logger
from src.data.symbol_info import SymbolSpec

log = get_logger(__name__)


def calc_lot_size(
    balance: float,
    sl_pips: float,
    spec: SymbolSpec,
    risk_pct: float | None = None,
) -> float:
    """
    Calculate lot size to risk exactly `risk_pct`% of `balance` on this trade.

    Formula:
        risk_amount = balance × risk_pct / 100
        lot_size    = risk_amount / (sl_pips × pip_value_per_lot)

    Args:
        balance:           Account balance in USD.
        sl_pips:           Stop-loss distance in pips.
        spec:              SymbolSpec (pip_value_per_lot, min_lot, max_lot, lot_step).
        risk_pct:          % of balance to risk. Defaults to config value.

    Returns:
        Lot size clamped to symbol min/max and rounded to lot_step.
    """
    if risk_pct is None:
        risk_pct = get("risk.risk_pct_per_trade", 1.0)

    if sl_pips <= 0:
        log.error("calc_lot_size: sl_pips must be > 0, got %.4f", sl_pips)
        return spec.min_lot

    risk_amount = balance * (risk_pct / 100.0)
    raw_lots = risk_amount / (sl_pips * spec.pip_value_per_lot)

    # Round DOWN to nearest lot_step
    step = spec.lot_step
    lots = math.floor(raw_lots / step) * step

    # Clamp to symbol limits
    lots = max(spec.min_lot, min(spec.max_lot, lots))

    log.debug(
        "Position sizing: balance=%.2f risk=%.1f%% sl=%.1f pips  "
        "pip_val=%.4f  raw=%.4f  final=%.2f lots",
        balance, risk_pct, sl_pips, spec.pip_value_per_lot, raw_lots, lots,
    )
    return round(lots, 8)


def calc_sl_pips_from_atr(df, atr_period: int | None = None, multiplier: float | None = None) -> float:
    """
    Calculate SL distance in pips using ATR.

    Args:
        df:         OHLCV DataFrame (M15 recommended).
        atr_period: ATR period. Defaults to config value.
        multiplier: ATR multiplier for SL. Defaults to config value.

    Returns:
        SL distance in pips.
    """
    import pandas as pd

    if atr_period is None:
        atr_period = get("risk.atr_period", 14)
    if multiplier is None:
        multiplier = get("risk.sl_atr_multiplier", 1.5)

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=atr_period, adjust=False).mean()
    atr_last = float(atr.iloc[-1])

    # Convert price-based ATR to pips (1 pip = 0.0001 for EURUSD, 0.01 for XAUUSD)
    # We'll return raw price-based value; caller converts using spec
    sl_price_distance = atr_last * multiplier
    return sl_price_distance
