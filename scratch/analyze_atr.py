import sys
import os
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from src.data.mt5_connection import connect, is_connected
from src.data.candles import get_candles

def calc_atr_series(df, period=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(span=period, adjust=False).mean()
    return atr

# 1. Historical Backtest ATR
hist_path = "data/historical/XAUUSD_M15.csv"
if os.path.exists(hist_path):
    df_hist = pd.read_csv(hist_path)
    # Ensure column names are lowercase
    df_hist.columns = [c.lower() for c in df_hist.columns]
    atr_hist = calc_atr_series(df_hist)
    avg_hist_atr = atr_hist.mean()
    last_hist_atr = atr_hist.iloc[-1]
    print(f"Historical XAUUSD M15 (Backtest):")
    print(f"  Rows: {len(df_hist)}")
    print(f"  Average ATR(14): {avg_hist_atr:.4f} ($)")
    print(f"  Last Hist ATR(14): {last_hist_atr:.4f} ($)")
else:
    print(f"Historical file not found: {hist_path}")

# 2. Live Current ATR
if not is_connected():
    connect()
if is_connected():
    df_live = get_candles("XAUUSD", "M15", count=300)
    atr_live = calc_atr_series(df_live)
    current_atr = atr_live.iloc[-1]
    print(f"\nLive Current XAUUSD M15:")
    print(f"  Current ATR(14): {current_atr:.4f} ($)")
    
    # Live SL Distance in pips = current_atr * multiplier * 100 (since 1 pip = 0.01 for gold)
    # config uses sl_atr_multiplier = 1.8
    multiplier = 1.8
    sl_dist = current_atr * multiplier
    sl_pips = sl_dist / 0.01
    print(f"  Expected SL Distance: {sl_dist:.4f} ($) / {sl_pips:.1f} pips")
else:
    print("MT5 not connected")
