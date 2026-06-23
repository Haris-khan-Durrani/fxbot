"""
src/backtest/engine.py
──────────────────────
Event-driven bar-by-bar backtesting engine.
Simulates fills with spread + commission. Tracks equity curve.

Performance: All indicators are pre-computed vectorially upfront (once).
The main loop does O(1) work per bar — total O(n) runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from src.backtest.strategy_functions import calc_atr, calc_ema, calc_rsi
from src.core.logger import get_logger
from src.data.symbol_info import get_symbol_spec
from src.risk.position_sizing import calc_lot_size

log = get_logger(__name__)


@dataclass
class BacktestTrade:
    open_bar: int
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    lot_size: float
    score: float
    close_bar: Optional[int] = None
    close_price: Optional[float] = None
    pnl_pips: float = 0.0
    pnl_usd: float = 0.0
    result: str = "OPEN"    # WIN | LOSS | OPEN


@dataclass
class BacktestState:
    balance: float
    equity_curve: list[float] = field(default_factory=list)
    trades: list[BacktestTrade] = field(default_factory=list)
    open_trade: Optional[BacktestTrade] = None





def _commission(symbol: str, lot_size: float, commission_per_lot: float) -> float:
    return lot_size * commission_per_lot  # Both sides already in per-lot cost


# ── Vectorized indicator pre-computation ─────────────────────────────

def _precompute_m15(df: pd.DataFrame, params: dict) -> dict:
    """Compute all M15 indicators once on the full series."""
    lookback = params.get("bos_lookback", 20)
    confirm  = params.get("bos_confirm", 2)
    sweep_lb = params.get("sweep_lookback", 20)
    sweep_wr = params.get("sweep_wick", 0.5)
    rsi_p    = params.get("rsi_period", 14)
    rsi_os   = params.get("rsi_oversold", 30)
    rsi_ob   = params.get("rsi_overbought", 70)
    rsi_mid  = params.get("rsi_mid", 50)
    atr_p    = params.get("atr_period", 14)
    min_brk  = params.get("bos_min_break_atr_ratio", 0.10)

    london_open = params.get("london_open", "08:00")
    london_close = params.get("london_close", "17:00")
    ny_open = params.get("ny_open", "13:00")
    ny_close = params.get("ny_close", "22:00")

    def _to_mins(time_str: str) -> int:
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    l_start = _to_mins(london_open)
    l_end = _to_mins(london_close)
    n_start = _to_mins(ny_open)
    n_end = _to_mins(ny_close)

    hours = df.index.hour
    minutes = df.index.minute
    total_minutes = hours * 60 + minutes

    in_london = (l_start <= total_minutes) & (total_minutes < l_end)
    in_ny = (n_start <= total_minutes) & (total_minutes < n_end)

    in_session = in_london | in_ny
    session_sc = np.zeros(len(df))
    session_sc[in_london & in_ny] = 1.0
    session_sc[in_london & ~in_ny] = 0.7
    session_sc[~in_london & in_ny] = 0.7

    n = len(df)
    close = df["close"].values
    high  = df["high"].values
    low   = df["low"].values

    # RSI
    rsi_s  = calc_rsi(df["close"], rsi_p).values
    # ATR
    atr_s  = calc_atr(df, atr_p).values

    # RSI momentum state per bar
    mom_state = np.empty(n, dtype=object)
    for i in range(n):
        r = rsi_s[i]
        if np.isnan(r):
            mom_state[i] = "NEUTRAL"
        elif r <= rsi_os:
            mom_state[i] = "OVERSOLD"
        elif r >= rsi_ob:
            mom_state[i] = "OVERBOUGHT"
        elif r >= rsi_mid:
            mom_state[i] = "BULLISH_NEUTRAL"
        else:
            mom_state[i] = "BEARISH_NEUTRAL"

    # BOS detection per bar (vectorized rolling)
    bos_dir  = np.full(n, "NONE", dtype=object)
    bos_conf = np.zeros(n)
    for i in range(lookback + confirm + 3, n):
        sw_high = high[i - confirm - lookback - 1 : i - confirm].max()
        sw_low  = low [i - confirm - lookback - 1 : i - confirm].min()
        rec_close = close[i - confirm : i]
        rng = high[i-1] - low[i-1]
        if rng < 1e-10:
            continue
        atr_val = atr_s[i-1]
        min_break = atr_val * min_brk if not np.isnan(atr_val) else 0.0

        if np.all(rec_close > sw_high):
            brk = float(rec_close[-1] - sw_high)
            if brk >= min_break:
                conf = min(1.0, brk / rng)
                bos_dir[i]  = "BULLISH"
                bos_conf[i] = max(0.5, conf)
        elif np.all(rec_close < sw_low):
            brk = float(sw_low - rec_close[-1])
            if brk >= min_break:
                conf = min(1.0, brk / rng)
                bos_dir[i]  = "BEARISH"
                bos_conf[i] = max(0.5, conf)

    # Sweep detection per bar
    sweep_dir  = np.full(n, "NONE", dtype=object)
    sweep_conf = np.zeros(n)
    for i in range(sweep_lb + 3, n):
        lb_slice_high = high[i - sweep_lb - 2 : i - 2]
        lb_slice_low  = low [i - sweep_lb - 2 : i - 2]
        sw_high = lb_slice_high.max()
        sw_low  = lb_slice_low.min()
        rng = high[i-1] - low[i-1]
        if rng < 1e-10:
            continue
        if low[i-1] < sw_low and close[i-1] > sw_low:
            wick = (sw_low - low[i-1]) / rng
            if wick >= sweep_wr:
                sweep_dir[i]  = "BULLISH"
                sweep_conf[i] = min(1.0, wick)
        elif high[i-1] > sw_high and close[i-1] < sw_high:
            wick = (high[i-1] - sw_high) / rng
            if wick >= sweep_wr:
                sweep_dir[i]  = "BEARISH"
                sweep_conf[i] = min(1.0, wick)

    return {
        "rsi": rsi_s,
        "atr": atr_s,
        "mom_state": mom_state,
        "bos_dir": bos_dir,
        "bos_conf": bos_conf,
        "sweep_dir": sweep_dir,
        "sweep_conf": sweep_conf,
        "in_session": in_session,
        "session_score": session_sc,
    }


def _precompute_h1(df: pd.DataFrame, params: dict) -> dict:
    """Compute H1 EMAs once on the full series with ATR-normalized separation."""
    fast = params.get("ema_fast", 50)
    slow = params.get("ema_slow", 200)
    ema_sep_threshold = params.get("ema_min_separation_atr_ratio", 0.005)

    ema_f = calc_ema(df["close"], fast).values
    ema_s = calc_ema(df["close"], slow).values
    atr_h1 = calc_atr(df, slow).values

    n = len(df)
    trend = np.full(n, "NEUTRAL", dtype=object)
    for i in range(n):
        f, s = ema_f[i], ema_s[i]
        if np.isnan(f) or np.isnan(s) or s == 0:
            trend[i] = "NEUTRAL"
            continue
        
        atr_val = atr_h1[i]
        min_sep = atr_val * ema_sep_threshold if not np.isnan(atr_val) else 0.0
        
        if abs(f - s) < min_sep:
            trend[i] = "NEUTRAL"
        elif f > s:
            trend[i] = "BULLISH"
        else:
            trend[i] = "BEARISH"

    return {
        "ema_fast": ema_f,
        "ema_slow": ema_s,
        "trend": trend,
        "index_ns": df.index.view("int64"),
    }


def _score_signal(
    trend: str,
    direction: str,
    bos_conf: float,
    sweep_dir: str,
    sweep_conf: float,
    mom_state: str,
    session_sc: float,
    weights: dict,
) -> float:
    """Compute 0-100 signal score from pre-computed components."""
    w = weights or {"trend": 30, "structure": 25, "liquidity": 20, "momentum": 15, "session": 10}
    total_w = sum(w.values())

    if trend == "NEUTRAL":
        s_trend = 0.5
    elif (trend == "BULLISH" and direction == "BUY") or (trend == "BEARISH" and direction == "SELL"):
        s_trend = 1.0
    else:
        s_trend = 0.0

    s_structure = bos_conf

    if sweep_dir != "NONE" and (
        (sweep_dir == "BULLISH" and direction == "BUY") or
        (sweep_dir == "BEARISH" and direction == "SELL")
    ):
        s_liquidity = sweep_conf
    else:
        s_liquidity = 0.0

    if direction == "BUY":
        s_mom_map = {"OVERSOLD": 1.0, "BULLISH_NEUTRAL": 0.8, "BEARISH_NEUTRAL": 0.5, "OVERBOUGHT": 0.3}
    else:
        s_mom_map = {"OVERBOUGHT": 1.0, "BEARISH_NEUTRAL": 0.8, "BULLISH_NEUTRAL": 0.5, "OVERSOLD": 0.3}
    s_momentum = s_mom_map.get(mom_state, 0.5)

    s_session = session_sc

    return (
        s_trend    * 100 * w.get("trend", 30) +
        s_structure * 100 * w.get("structure", 25) +
        s_liquidity * 100 * w.get("liquidity", 20) +
        s_momentum  * 100 * w.get("momentum", 15) +
        s_session   * 100 * w.get("session", 10)
    ) / total_w


# ── Main backtest engine ──────────────────────────────────────────────

def run_backtest(
    symbol: str,
    df_m15: pd.DataFrame,
    df_h1: pd.DataFrame,
    params: dict,
    initial_balance: float = 10_000.0,
    commission_per_lot: float = 7.0,
    spread_pips: float = 1.0,
    risk_pct: float = 1.0,
    tp_rr: float = 2.0,
    min_score: float = 65.0,
    warmup_bars: int = 250,
) -> BacktestState:
    """
    Run bar-by-bar backtest on M15 data.
    All indicators pre-computed vectorially — O(n) total runtime.
    """
    state = BacktestState(balance=initial_balance)
    spec = get_symbol_spec(symbol)
    pip_size = spec.point * 10
    pip_val  = spec.pip_value_per_lot
    spread_price = spread_pips * pip_size
    sl_atr_mult = params.get("sl_atr_mult", 1.5)
    weights = params.get("score_weights", {})

    # ── Pre-compute all indicators once ──────────────────────────────
    log.info("Pre-computing M15 indicators for %s (%d bars)...", symbol, len(df_m15))
    m15_ind = _precompute_m15(df_m15, params)
    log.info("Pre-computing H1 indicators for %s (%d bars)...", symbol, len(df_h1))
    h1_ind  = _precompute_h1(df_h1, params)
    log.info("Indicators ready. Starting bar loop...")

    m15_times_ns = df_m15.index.view("int64")
    h1_times_ns  = h1_ind["index_ns"]

    n = len(df_m15)

    high_vals = df_m15["high"].values
    low_vals = df_m15["low"].values
    close_vals = df_m15["close"].values

    for i in range(warmup_bars, n):
        bar_high  = high_vals[i]
        bar_low   = low_vals[i]
        bar_close = close_vals[i]

        # ── Check open trade SL/TP ────────────────────────────────────
        if state.open_trade is not None:
            trade  = state.open_trade
            closed = False
            if trade.direction == "BUY":
                if bar_low <= trade.sl_price:
                    _close_trade(trade, trade.sl_price, i, state, pip_size, pip_val, commission_per_lot, "LOSS")
                    closed = True
                elif bar_high >= trade.tp_price:
                    _close_trade(trade, trade.tp_price, i, state, pip_size, pip_val, commission_per_lot, "WIN")
                    closed = True
            else:
                if bar_high >= trade.sl_price:
                    _close_trade(trade, trade.sl_price, i, state, pip_size, pip_val, commission_per_lot, "LOSS")
                    closed = True
                elif bar_low <= trade.tp_price:
                    _close_trade(trade, trade.tp_price, i, state, pip_size, pip_val, commission_per_lot, "WIN")
                    closed = True
            if closed:
                state.open_trade = None
                state.equity_curve.append(state.balance)
                continue

        # ── No open trade — evaluate signal ──────────────────────────
        if state.open_trade is None:
            # O(1) indicator lookups
            bos_d = m15_ind["bos_dir"][i]
            if bos_d == "NONE":
                state.equity_curve.append(state.balance)
                continue

            direction = "BUY" if bos_d == "BULLISH" else "SELL"
            bos_c     = m15_ind["bos_conf"][i]
            sw_d      = m15_ind["sweep_dir"][i]
            sw_c      = m15_ind["sweep_conf"][i]
            mom       = m15_ind["mom_state"][i]
            atr_val   = m15_ind["atr"][i]

            # Sweep must agree if detected
            if sw_d not in ("NONE", bos_d):
                state.equity_curve.append(state.balance)
                continue

            # O(log n) H1 trend lookup
            cur_ns = int(m15_times_ns[i])
            h1_idx = int(np.searchsorted(h1_times_ns, cur_ns, side="right")) - 1
            if h1_idx < 200:
                state.equity_curve.append(state.balance)
                continue
            trend = h1_ind["trend"][h1_idx]

            # Session filter gate
            in_sess = m15_ind["in_session"][i]
            trade_only_in_session = params.get("trade_only_in_session", True)
            if trade_only_in_session and not in_sess:
                state.equity_curve.append(state.balance)
                continue

            session_sc = m15_ind["session_score"][i]
            score = _score_signal(trend, direction, bos_c, sw_d, sw_c, mom, session_sc, weights)

            if score < min_score:
                state.equity_curve.append(state.balance)
                continue

            # ATR-based SL
            if np.isnan(atr_val) or atr_val <= 0:
                state.equity_curve.append(state.balance)
                continue
            sl_distance = atr_val * sl_atr_mult

            entry = bar_close + spread_price if direction == "BUY" else bar_close - spread_price
            if direction == "BUY":
                sl = entry - sl_distance
                tp = entry + sl_distance * tp_rr
            else:
                sl = entry + sl_distance
                tp = entry - sl_distance * tp_rr

            sl_pips = sl_distance / pip_size
            if sl_pips <= 0:
                state.equity_curve.append(state.balance)
                continue

            lot_size = calc_lot_size(state.balance, sl_pips, spec, risk_pct)

            comm = _commission(symbol, lot_size, commission_per_lot)
            state.balance -= comm

            trade = BacktestTrade(
                open_bar=i, direction=direction,
                entry_price=entry, sl_price=sl, tp_price=tp,
                lot_size=lot_size, score=round(score, 2),
            )
            state.open_trade = trade
            state.trades.append(trade)

        state.equity_curve.append(state.balance)

    # Close any still-open trade at the last bar
    if state.open_trade is not None:
        last_close = df_m15.iloc[-1]["close"]
        _close_trade(state.open_trade, last_close, n - 1, state, pip_size, pip_val, commission_per_lot, "OPEN")
        state.open_trade = None

    log.info("Backtest complete for %s: %d trades, final balance=%.2f",
             symbol, len(state.trades), state.balance)
    return state


def _close_trade(
    trade: BacktestTrade, close_price: float, bar_idx: int,
    state: BacktestState, pip_size: float, pip_val: float,
    commission: float, result: str,
) -> None:
    if trade.direction == "BUY":
        pips = (close_price - trade.entry_price) / pip_size
    else:
        pips = (trade.entry_price - close_price) / pip_size

    pnl = pips * pip_val * trade.lot_size

    trade.close_bar  = bar_idx
    trade.close_price = close_price
    trade.pnl_pips   = round(pips, 1)
    trade.pnl_usd    = round(pnl, 2)
    trade.result     = result
    state.balance   += pnl
