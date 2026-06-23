"""
src/backtest/metrics.py
───────────────────────
Performance metrics from a completed backtest.
Outputs: win rate, profit factor, max drawdown, Sharpe, expectancy.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from src.backtest.engine import BacktestState, BacktestTrade
from src.core.logger import get_logger

log = get_logger(__name__)


@dataclass
class BacktestMetrics:
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float          # %
    profit_factor: float     # Gross profit / Gross loss
    expectancy_usd: float    # Average P&L per trade in USD
    max_drawdown_pct: float  # % from peak equity
    sharpe_ratio: float      # Annualized Sharpe (assuming M15 bars)
    total_pnl_usd: float
    final_balance: float
    initial_balance: float
    return_pct: float        # Total return %
    avg_win_pips: float
    avg_loss_pips: float
    avg_rr: float            # Actual risk-reward achieved
    passes_gate: bool        # True if meets min_pf and max_dd thresholds


def compute_metrics(
    state: BacktestState,
    initial_balance: float,
    min_profit_factor: float = 1.2,
    max_drawdown_pct: float = 20.0,
) -> BacktestMetrics:
    """Compute all performance metrics from a BacktestState."""
    closed_trades = [t for t in state.trades if t.result in ("WIN", "LOSS")]

    if not closed_trades:
        return _empty_metrics(initial_balance)

    wins = [t for t in closed_trades if t.result == "WIN"]
    losses = [t for t in closed_trades if t.result == "LOSS"]

    win_rate = len(wins) / len(closed_trades) * 100
    gross_profit = sum(t.pnl_usd for t in wins)
    gross_loss = abs(sum(t.pnl_usd for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    all_pnl = [t.pnl_usd for t in closed_trades]
    expectancy = float(np.mean(all_pnl)) if all_pnl else 0.0

    # Max drawdown from equity curve
    equity = np.array(state.equity_curve)
    if len(equity) > 0:
        rolling_max = np.maximum.accumulate(equity)
        drawdowns = (rolling_max - equity) / rolling_max * 100
        max_dd = float(drawdowns.max())
    else:
        max_dd = 0.0

    # Sharpe ratio (bar-level returns, annualized)
    bar_returns = np.diff(equity) / equity[:-1] if len(equity) > 1 else np.array([0.0])
    if bar_returns.std() > 0:
        # M15 bars per year ≈ 4 × 24 × 252 = 24192
        sharpe = (bar_returns.mean() / bar_returns.std()) * np.sqrt(24192)
    else:
        sharpe = 0.0

    total_pnl = state.balance - initial_balance
    return_pct = total_pnl / initial_balance * 100

    avg_win_pips = float(np.mean([t.pnl_pips for t in wins])) if wins else 0.0
    avg_loss_pips = float(np.mean([t.pnl_pips for t in losses])) if losses else 0.0
    avg_rr = abs(avg_win_pips / avg_loss_pips) if avg_loss_pips != 0 else 0.0

    passes = profit_factor >= min_profit_factor and max_dd <= max_drawdown_pct

    return BacktestMetrics(
        total_trades=len(closed_trades),
        win_trades=len(wins),
        loss_trades=len(losses),
        win_rate=round(win_rate, 2),
        profit_factor=round(profit_factor, 3),
        expectancy_usd=round(expectancy, 2),
        max_drawdown_pct=round(max_dd, 2),
        sharpe_ratio=round(sharpe, 3),
        total_pnl_usd=round(total_pnl, 2),
        final_balance=round(state.balance, 2),
        initial_balance=initial_balance,
        return_pct=round(return_pct, 2),
        avg_win_pips=round(avg_win_pips, 1),
        avg_loss_pips=round(avg_loss_pips, 1),
        avg_rr=round(avg_rr, 2),
        passes_gate=passes,
    )


def _empty_metrics(initial_balance: float) -> BacktestMetrics:
    return BacktestMetrics(
        total_trades=0, win_trades=0, loss_trades=0,
        win_rate=0.0, profit_factor=0.0, expectancy_usd=0.0,
        max_drawdown_pct=0.0, sharpe_ratio=0.0,
        total_pnl_usd=0.0, final_balance=initial_balance,
        initial_balance=initial_balance, return_pct=0.0,
        avg_win_pips=0.0, avg_loss_pips=0.0, avg_rr=0.0, passes_gate=False,
    )


def print_metrics_table(symbol: str, metrics: BacktestMetrics) -> None:
    """Print a formatted metrics table to stdout."""
    gate = "✅ PASSES GATE" if metrics.passes_gate else "❌ FAILS GATE — re-tune before proceeding"
    print(f"\n{'─' * 55}")
    print(f"  Backtest Results — {symbol}")
    print(f"{'─' * 55}")
    print(f"  Total Trades      {metrics.total_trades:>10}")
    print(f"  Wins / Losses     {metrics.win_trades:>4} W / {metrics.loss_trades:>4} L")
    print(f"  Win Rate          {metrics.win_rate:>9.1f}%")
    print(f"  Profit Factor     {metrics.profit_factor:>10.3f}")
    print(f"  Expectancy        {metrics.expectancy_usd:>+9.2f} USD/trade")
    print(f"  Avg Win           {metrics.avg_win_pips:>+9.1f} pips")
    print(f"  Avg Loss          {metrics.avg_loss_pips:>+9.1f} pips")
    print(f"  Avg R:R           {metrics.avg_rr:>10.2f}")
    print(f"  Max Drawdown      {metrics.max_drawdown_pct:>9.2f}%")
    print(f"  Sharpe Ratio      {metrics.sharpe_ratio:>10.3f}")
    print(f"  Total Return      {metrics.return_pct:>+9.2f}%")
    print(f"  Final Balance     ${metrics.final_balance:>10,.2f}")
    print(f"  Gate Assessment   {gate}")
    print(f"{'─' * 55}\n")
