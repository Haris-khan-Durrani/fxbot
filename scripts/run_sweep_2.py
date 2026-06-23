"""
scripts/run_sweep_2.py
──────────────────────
Runs a parameter sweep of 18 combinations (BOS confirm x SL multiplier x Min Score)
across all 3 symbols (EURUSD, GBPUSD, XAUUSD) over the 2.5-year historical data.
Outputs a markdown table of all results.
"""
import sys
import time
import itertools
from pathlib import Path
import pandas as pd

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import load_config
from src.backtest.data_loader import load_csv
from src.backtest.engine import run_backtest
from src.backtest.metrics import compute_metrics

def main():
    load_config()
    symbols = ["XAUUSD", "EURUSD", "GBPUSD"]
    
    # Load data for all symbols
    data = {}
    for sym in symbols:
        try:
            data[sym] = (load_csv(sym, "M15"), load_csv(sym, "H1"))
        except FileNotFoundError as e:
            print(f"Skipping {sym} due to missing data: {e}")
            
    # Sweep space: 2 * 3 * 3 = 18 combinations
    bos_confirms = [1, 2]
    sl_multipliers = [1.2, 1.5, 1.8]
    min_scores = [60.0, 65.0, 70.0]
    
    combos = list(itertools.product(bos_confirms, sl_multipliers, min_scores))
    print(f"Starting parameter sweep with {len(combos)} combinations per symbol...")
    
    results = []
    
    for sym in symbols:
        if sym not in data:
            continue
        df_m15, df_h1 = data[sym]
        
        for bos_c, sl_m, min_s in combos:
            params = {
                "ema_fast": 50,
                "ema_slow": 200,
                "bos_lookback": 20,
                "bos_confirm": bos_c,
                "sweep_lookback": 20,
                "sweep_wick": 0.5,
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "rsi_neutral_low": 40,
                "rsi_neutral_high": 60,
                "sl_atr_mult": sl_m,
                "atr_period": 14,
                "score_weights": {"trend": 30, "structure": 25, "liquidity": 20, "momentum": 15, "session": 10},
                "london_open": "08:00",
                "london_close": "17:00",
                "ny_open": "13:00",
                "ny_close": "22:00",
                "trade_only_in_session": True,
                "ema_min_separation_atr_ratio": 0.005,
            }
            
            t0 = time.monotonic()
            state = run_backtest(
                symbol=sym,
                df_m15=df_m15,
                df_h1=df_h1,
                params=params,
                initial_balance=10000.0,
                commission_per_lot=7.0,
                spread_pips=0.5,
                risk_pct=1.0,
                tp_rr=2.0,
                min_score=min_s,
            )
            elapsed = time.monotonic() - t0
            
            metrics = compute_metrics(state, 10000.0, 1.2, 20.0)
            
            results.append({
                "Symbol": sym,
                "BOS Confirm": bos_c,
                "SL Mult": sl_m,
                "Min Score": min_s,
                "Trades": metrics.total_trades,
                "WR%": f"{metrics.win_rate:.1f}%",
                "PF": f"{metrics.profit_factor:.3f}",
                "Max DD%": f"{metrics.max_drawdown_pct:.1f}%",
                "Return%": f"{metrics.return_pct:.1f}%",
                "Pass Gate": "✅" if metrics.passes_gate else "❌",
            })
            print(f"[{sym}] bos_c={bos_c} sl_m={sl_m} min_s={min_s} | trades={metrics.total_trades} PF={metrics.profit_factor:.3f} ret={metrics.return_pct:.1f}% | {elapsed:.1f}s")
            
    df_res = pd.DataFrame(results)
    out_csv = Path("data/historical") / "sweep_results_2.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nSweep completed. Results saved to {out_csv}")
    
    # Print tables per symbol
    for sym in symbols:
        print(f"\n{'='*40}\nResults for {sym}\n{'='*40}")
        df_sym = df_res[df_res["Symbol"] == sym]
        print(df_sym.to_markdown(index=False))

if __name__ == "__main__":
    main()
