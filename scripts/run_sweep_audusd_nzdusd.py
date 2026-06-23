"""
scripts/run_sweep_audusd_nzdusd.py
───────────────────────────────────
Runs the same 54-combination parameter sweep used for XAUUSD/EURUSD/GBPUSD,
applied to AUDUSD and NZDUSD.

  Grid: BOS confirm (1,2) × SL mult (1.2,1.5,1.8) × Min Score (60,65,70) = 18 combos
  Gate: PF ≥ 1.2 AND MaxDD ≤ 20%
  Period: 2024-01-01 → 2026-06-16 (same as Phase 0 sweep)

Output: ranked table per symbol. Any pair that fails ALL 18 combinations stays
permanently blocked in validated_symbols until the strategy is redesigned.
"""
import sys
import time
import itertools
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import load_config
from src.backtest.data_loader import load_csv
from src.backtest.engine import run_backtest
from src.backtest.metrics import compute_metrics


def main():
    load_config()
    symbols = ["AUDUSD", "NZDUSD"]

    # ── Load data ─────────────────────────────────────────────────────────────
    data = {}
    for sym in symbols:
        try:
            data[sym] = (load_csv(sym, "M15"), load_csv(sym, "H1"))
            print(f"✅ Loaded data for {sym}")
        except FileNotFoundError as e:
            print(f"❌ Skipping {sym} — missing CSV: {e}")

    if not data:
        print("No data available. Ensure AUDUSD and NZDUSD CSVs are in data/historical/.")
        sys.exit(1)

    # ── Parameter grid: identical to run_sweep_2.py ───────────────────────────
    bos_confirms  = [1, 2]
    sl_multipliers = [1.2, 1.5, 1.8]
    min_scores    = [60.0, 65.0, 70.0]

    combos = list(itertools.product(bos_confirms, sl_multipliers, min_scores))
    print(f"\nStarting sweep: {len(combos)} combinations × {len(data)} symbols = {len(combos)*len(data)} runs")
    print("Gate: PF ≥ 1.20 AND MaxDD ≤ 20.0%\n")

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
            gate = "✅ PASS" if metrics.passes_gate else "❌ FAIL"

            results.append({
                "Symbol":      sym,
                "BOS Confirm": bos_c,
                "SL Mult":     sl_m,
                "Min Score":   min_s,
                "Trades":      metrics.total_trades,
                "WR%":         f"{metrics.win_rate:.1f}%",
                "PF":          f"{metrics.profit_factor:.3f}",
                "Max DD%":     f"{metrics.max_drawdown_pct:.1f}%",
                "Return%":     f"{metrics.return_pct:.1f}%",
                "Pass Gate":   gate,
            })
            print(
                f"[{sym}] bos_c={bos_c} sl_m={sl_m} min_s={min_s} | "
                f"trades={metrics.total_trades} PF={metrics.profit_factor:.3f} "
                f"DD={metrics.max_drawdown_pct:.1f}% ret={metrics.return_pct:.1f}% "
                f"{gate} | {elapsed:.1f}s"
            )

    df_res = pd.DataFrame(results)
    out_csv = Path("data/historical") / "sweep_audusd_nzdusd.csv"
    df_res.to_csv(out_csv, index=False)
    print(f"\nResults saved to {out_csv}")

    # ── Summary tables ────────────────────────────────────────────────────────
    for sym in symbols:
        if sym not in data:
            continue
        df_sym = df_res[df_res["Symbol"] == sym].copy()
        passing = df_sym[df_sym["Pass Gate"] == "✅ PASS"]
        failing = df_sym[df_sym["Pass Gate"] == "❌ FAIL"]

        print(f"\n{'='*70}")
        print(f"{sym} — {len(passing)}/{len(df_sym)} combinations PASS the gate")
        print(f"{'='*70}")

        if passing.empty:
            print("  ⛔ ALL 18 combinations FAILED — symbol must stay BLOCKED in validated_symbols.")
            print("     Do not add to validated_symbols until strategy is redesigned for this pair.")
        else:
            print(f"  ✅ {len(passing)} combinations pass. Best results (sorted by PF):")
            # Sort by PF numerically for ranking
            df_sym["_pf"] = df_sym["PF"].str.replace("inf", "999").astype(float)
            top = df_sym.sort_values("_pf", ascending=False).drop(columns=["_pf"])
            print(top.to_markdown(index=False))

    # ── Final verdict ─────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("FINAL VERDICT")
    print(f"{'='*70}")
    for sym in symbols:
        if sym not in data:
            print(f"  {sym}: NO DATA — cannot evaluate")
            continue
        df_sym = df_res[df_res["Symbol"] == sym]
        passing = df_sym[df_sym["Pass Gate"] == "✅ PASS"]
        if passing.empty:
            print(f"  {sym}: ⛔ BLOCKED — 0/18 pass the gate. Do NOT add to validated_symbols.")
        else:
            # Best combo
            df_sym2 = df_sym.copy()
            df_sym2["_pf"] = df_sym2["PF"].str.replace("inf", "999").astype(float)
            best = df_sym2.sort_values("_pf", ascending=False).iloc[0]
            print(f"  {sym}: ✅ ELIGIBLE — {len(passing)}/18 pass. Best: "
                  f"BOS={best['BOS Confirm']} SL={best['SL Mult']} Score={best['Min Score']} "
                  f"PF={best['PF']} DD={best['Max DD%']}")


if __name__ == "__main__":
    main()
