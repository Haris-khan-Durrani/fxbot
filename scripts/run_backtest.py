"""
scripts/run_backtest.py
───────────────────────
CLI entry point for Phase 0 backtesting.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --pair XAUUSD --tf M15
    python scripts/run_backtest.py --pair XAUUSD EURUSD GBPUSD

Expects CSV files in data/historical/{SYMBOL}_{TIMEFRAME}.csv
Export from MT5: File → Open Data Folder → history → ...
Or download from Dukascopy (https://www.dukascopy.com/trading-tools/widgets/tools/tick_downloader/)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.data_loader import load_csv
from src.backtest.engine import run_backtest
from src.backtest.metrics import compute_metrics, print_metrics_table
from src.core.config import get, load_config
from src.core.logger import get_logger, setup_root_logger

setup_root_logger()
log = get_logger(__name__)

# Default strategy params from config.yaml
def _build_params() -> dict:
    return {
        "ema_fast": get("strategy.trend.ema_fast", 50),
        "ema_slow": get("strategy.trend.ema_slow", 200),
        "bos_lookback": get("strategy.structure.bos_lookback_bars", 20),
        "bos_confirm": get("strategy.structure.bos_confirmation_bars", 2),
        "sweep_lookback": get("strategy.liquidity.sweep_lookback_bars", 15),
        "sweep_wick": get("strategy.liquidity.sweep_wick_ratio", 0.5),
        "rsi_period": get("strategy.momentum.rsi_period", 14),
        "rsi_oversold": get("strategy.momentum.rsi_oversold", 30),
        "rsi_overbought": get("strategy.momentum.rsi_overbought", 70),
        "rsi_neutral_low": get("strategy.momentum.rsi_neutral_low", 40),
        "rsi_neutral_high": get("strategy.momentum.rsi_neutral_high", 60),
        "sl_atr_mult": get("risk.sl_atr_multiplier", 1.5),
        "atr_period": get("risk.atr_period", 14),
        "score_weights": get("scoring.weights", {}),
        "london_open": get("strategy.session.london_open", "08:00"),
        "london_close": get("strategy.session.london_close", "17:00"),
        "ny_open": get("strategy.session.ny_open", "13:00"),
        "ny_close": get("strategy.session.ny_close", "22:00"),
        "trade_only_in_session": get("strategy.session.trade_only_in_session", True),
        "ema_min_separation_atr_ratio": get("strategy.trend.ema_min_separation_atr_ratio", 0.005),
    }


def main():
    parser = argparse.ArgumentParser(
        description="FX Bot Phase 0 — Backtesting Harness"
    )
    parser.add_argument(
        "--pair", nargs="+", default=["XAUUSD", "EURUSD", "GBPUSD"],
        help="Symbols to backtest (default: XAUUSD EURUSD GBPUSD)"
    )
    parser.add_argument(
        "--tf", default="M15", help="Entry timeframe (default: M15)"
    )
    parser.add_argument(
        "--trend-tf", default="H1", help="Trend timeframe (default: H1)"
    )
    parser.add_argument(
        "--balance", type=float, default=None,
        help="Starting balance (default: from config.yaml)"
    )
    parser.add_argument(
        "--risk", type=float, default=None,
        help="Risk %% per trade (default: from config.yaml)"
    )
    parser.add_argument(
        "--min-score", type=float, default=None,
        help="Minimum signal score threshold (default: from config.yaml)"
    )
    parser.add_argument(
        "--save-equity", action="store_true",
        help="Save equity curves to data/historical/{SYMBOL}_equity.csv"
    )
    args = parser.parse_args()

    cfg = load_config()
    initial_balance = args.balance or get("backtest.initial_balance", 10000)
    risk_pct = args.risk or get("risk.risk_pct_per_trade", 1.0)
    min_score = args.min_score or get("scoring.min_score", 65.0)
    commission = get("backtest.commission_per_lot", 7.0)
    spread = get("backtest.slippage_pips", 0.5)
    tp_rr = get("risk.tp_risk_reward", 2.0)
    min_pf = get("backtest.min_profit_factor", 1.2)
    max_dd = get("backtest.max_drawdown_pct", 20.0)

    params = _build_params()
    print(f"\n{'═' * 55}")
    print(f"  FX Bot — Phase 0 Backtesting Harness")
    print(f"  Pairs: {', '.join(args.pair)}")
    print(f"  Balance: ${initial_balance:,.0f}  Risk: {risk_pct}%  MinScore: {min_score}")
    print(f"  Commission: ${commission}/lot  Spread: {spread} pips  TP RR: {tp_rr}:1")
    print(f"{'═' * 55}\n")

    all_pass = []

    for symbol in args.pair:
        print(f"\n⏳ Loading data for {symbol} ...")
        try:
            df_m15 = load_csv(symbol, args.tf)
            df_h1 = load_csv(symbol, args.trend_tf)
        except FileNotFoundError as e:
            print(f"\n❌ {e}\n")
            print("How to get data:")
            print("  1. Open MT5 → Tools → History Center → select symbol/timeframe → Export")
            print("  2. Save file as:  data/historical/{SYMBOL}_{TIMEFRAME}.csv")
            print("  3. Example:  data/historical/XAUUSD_M15.csv")
            continue

        print(f"  M15: {len(df_m15):,} bars  |  H1: {len(df_h1):,} bars")
        print(f"  Running backtest ...")

        import pandas as pd
        state = run_backtest(
            symbol=symbol,
            df_m15=df_m15,
            df_h1=df_h1,
            params=params,
            initial_balance=initial_balance,
            commission_per_lot=commission,
            spread_pips=spread,
            risk_pct=risk_pct,
            tp_rr=tp_rr,
            min_score=min_score,
        )

        metrics = compute_metrics(state, initial_balance, min_pf, max_dd)
        print_metrics_table(symbol, metrics)
        all_pass.append(metrics.passes_gate)

        if args.save_equity and state.equity_curve:
            out = Path(__file__).parent.parent / "data" / "historical" / f"{symbol}_equity.csv"
            import pandas as pd
            pd.Series(state.equity_curve, name="equity").to_csv(out)
            print(f"  Equity curve saved: {out}")

    # Overall gate decision
    passing = sum(all_pass)
    total = len(all_pass)
    print(f"\n{'═' * 55}")
    if total == 0:
        print("  ⚠️  No symbols could be backtested (missing CSV data files).")
        print("  See instructions above to export historical data from MT5.")
    elif passing >= max(1, total - 1):  # Allow 1 pair to fail
        print(f"  ✅ GATE PASSED ({passing}/{total} pairs pass) — safe to build Phase 1+")
    else:
        print(f"  ❌ GATE FAILED ({passing}/{total} pairs pass)")
        print("  Adjust parameters in config.yaml and re-run before building live infrastructure.")
    print(f"{'═' * 55}\n")


if __name__ == "__main__":
    main()
