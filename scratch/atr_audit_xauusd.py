"""
scratch/atr_audit_xauusd.py
────────────────────────────
Audits XAUUSD M15 ATR(14) across:
  - The full 2.5-year backtest period (2024-01-01 → 2026-06-16)
  - Recent 4 weeks (approx last 28 calendar days from the CSV)
  - Reports percentile distribution and whether 161-pip stop is an outlier
  - Reports how many backtest trades would be blocked by a max_atr_pips cap
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np

# ── Load XAUUSD M15 backtest CSV ─────────────────────────────────────────────
csv_path = Path("data/historical/XAUUSD_M15.csv")
if not csv_path.exists():
    print(f"ERROR: {csv_path} not found. Ensure backtest data is present.")
    sys.exit(1)

df = pd.read_csv(csv_path, parse_dates=["time"])
df = df.sort_values("time").reset_index(drop=True)

print(f"Loaded {len(df):,} rows from {df['time'].iloc[0].date()} -> {df['time'].iloc[-1].date()}")

# ── Compute ATR(14) in pips (XAUUSD: 1 pip = $0.10, price move of 0.10 = 1 pip; M15 bar ATR in price units)
# For XAUUSD, ATR is in price (USD per oz). 1 pip = 0.01 price movement = 10 pip per dollar.
# In our system: pip_size = 0.01 for XAUUSD (point * 10 where point = 0.001 for gold), so 1 pip = $0.10 move
# BUT in the SL calculation, for XAUUSD we use sl_atr_multiplier * ATR in price directly.
# Let's report ATR in both price units AND "pips" (price / 0.01) for direct comparison to the 161-pip stop.

def calc_atr(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

df["atr"] = calc_atr(df, period=14)

# XAUUSD pip convention: 1 pip = point * 10 = 0.01 * 10 = 0.10 USD price move
# This matches main.py line 142: pip_size = spec.point * 10
# (spec.point for XAUUSD = 0.01, so pip_size = 0.10)
# A $1.00 price move = 10 pips. ATR of $1.61 (price) = 16.1 pips.
PIP_SIZE = 0.10
df["atr_pips"] = df["atr"] / PIP_SIZE

# ── Full backtest period stats ────────────────────────────────────────────────
print("\n" + "="*60)
print("XAUUSD M15 ATR(14) — FULL BACKTEST PERIOD (2024-01-01 → 2026-06-16)")
print("="*60)
bt_mask = (df["time"] >= "2024-01-01") & (df["time"] <= "2026-06-16")
bt_atr = df.loc[bt_mask, "atr_pips"].dropna()

print(f"  Bars in period:     {len(bt_atr):,}")
print(f"  Mean ATR (pips):    {bt_atr.mean():.1f}")
print(f"  Median ATR (pips):  {bt_atr.median():.1f}")
print(f"  Std Dev (pips):     {bt_atr.std():.1f}")
print(f"  Min ATR (pips):     {bt_atr.min():.1f}")
print(f"  Max ATR (pips):     {bt_atr.max():.1f}")
print(f"  P50 (pips):         {bt_atr.quantile(0.50):.1f}")
print(f"  P75 (pips):         {bt_atr.quantile(0.75):.1f}")
print(f"  P90 (pips):         {bt_atr.quantile(0.90):.1f}")
print(f"  P95 (pips):         {bt_atr.quantile(0.95):.1f}")
print(f"  P99 (pips):         {bt_atr.quantile(0.99):.1f}")

# ── Recent 4 weeks stats ──────────────────────────────────────────────────────
recent_cutoff = df["time"].max() - pd.Timedelta(days=28)
recent_mask = df["time"] >= recent_cutoff
recent_atr = df.loc[recent_mask, "atr_pips"].dropna()

print(f"\n{'='*60}")
print(f"XAUUSD M15 ATR(14) — RECENT 4 WEEKS (from {recent_cutoff.date()})")
print("="*60)
print(f"  Bars in period:     {len(recent_atr):,}")
print(f"  Mean ATR (pips):    {recent_atr.mean():.1f}")
print(f"  Median ATR (pips):  {recent_atr.median():.1f}")
print(f"  P50 (pips):         {recent_atr.quantile(0.50):.1f}")
print(f"  P90 (pips):         {recent_atr.quantile(0.90):.1f}")
print(f"  P95 (pips):         {recent_atr.quantile(0.95):.1f}")

# ── Verdict on 161-pip stop ───────────────────────────────────────────────────
print(f"\n{'='*60}")
print("VERDICT: 161-pip stop vs ATR distribution")
print("="*60)
stop_pips = 161.0
pct_below = (bt_atr < stop_pips).mean() * 100
print(f"  161-pip stop is at the {pct_below:.1f}th percentile of ATR values")
print(f"  → {100-pct_below:.1f}% of M15 bars had ATR > 161 pips")
if pct_below > 95:
    print("  → OUTLIER: 161 pips is in the top 5% of ATR values — extreme volatility event")
elif pct_below > 80:
    print("  → ELEVATED: 161 pips is in the top 20% of ATR values — high but not extreme")
else:
    print("  → NORMAL: 161 pips is within the typical ATR range")

# ── Impact of max_atr_pips cap on backtest entries ────────────────────────────
# In the bot: sl_price_dist = ATR_price * SL_ATR_MULT
#             sl_pips       = sl_price_dist / PIP_SIZE (0.10)
# A max_atr_pips cap of X means: skip entry if (ATR_price * SL_ATR_MULT) / 0.10 > X
# Rearranged: ATR_price > (X * 0.10) / SL_ATR_MULT
# i.e., ATR_pips > X / SL_ATR_MULT

print("\n--- Impact of max_atr_pips cap on backtest entries ---")
SL_ATR_MULT = 1.8

# The live stop of 161 pips in price = 161 * 0.10 = $16.10 price distance
# That was caused by ATR_price = 16.10 / 1.8 = $8.94, i.e., 89.4 pips
print(f"\n  Contextual: the live 161-pip stop = $16.10 price distance")
print(f"  ATR at that entry: {16.10 / SL_ATR_MULT:.2f} USD = {(16.10 / SL_ATR_MULT) / PIP_SIZE:.1f} pips (ATR in pips)")
pct_at_161 = (bt_atr < 161).mean() * 100
print(f"  161-pip ATR is at the {pct_at_161:.1f}th percentile of historical ATR(pips)")

for cap in [100, 120, 150, 175, 200]:
    atr_threshold_pips = cap / SL_ATR_MULT   # ATR in pips above which the entry is blocked
    blocked_pct = (bt_atr > atr_threshold_pips).mean() * 100
    print(f"\n  max_atr_pips={cap}: blocks entries where ATR > {atr_threshold_pips:.1f} pips")
    print(f"    -> Would block {blocked_pct:.1f}% of M15 bars during backtest")
    if blocked_pct > 20:
        print(f"    WARNING: TOO TIGHT -- blocks >20% of entries, kills signal frequency")
    elif blocked_pct > 10:
        print(f"    WARNING: MODERATE -- blocks 10-20% of entries, watch signal frequency")
    else:
        print(f"    OK: REASONABLE -- blocks <10% of extreme-volatility entries")

print("\nDone.")
