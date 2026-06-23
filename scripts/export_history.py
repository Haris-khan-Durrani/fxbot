"""
scripts/export_history.py
─────────────────────────
Export historical data (M15 and H1) from MT5 for backtesting.
Saves CSV files directly to data/historical/ directory.
Downloads data from 2024-01-01 to today (~2.5 years).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import MetaTrader5 as mt5
import src.data.mt5_connection as mt5_conn

# Symbols to download
SYMBOLS = ["XAUUSD", "EURUSD", "GBPUSD"]
START_DATE = datetime(2024, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime.now(timezone.utc)

def export_symbol_history(symbol: str):
    print(f"\nProcessing {symbol}...")
    
    # 1. Download H1 data
    print("  Downloading H1 rates...")
    rates_h1 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_H1, START_DATE, END_DATE)
    if rates_h1 is None or len(rates_h1) == 0:
        print(f"  [ERROR] Failed to download H1 data for {symbol}: {mt5.last_error()}")
    else:
        df_h1 = pd.DataFrame(rates_h1)
        df_h1['time'] = pd.to_datetime(df_h1['time'], unit='s')
        out_h1 = Path("data/historical") / f"{symbol}_H1.csv"
        df_h1.to_csv(out_h1, index=False)
        print(f"  [SUCCESS] Exported H1: {len(df_h1):,} bars to {out_h1}")

    # 2. Download M15 data
    print("  Downloading M15 rates...")
    rates_m15 = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M15, START_DATE, END_DATE)
    if rates_m15 is None or len(rates_m15) == 0:
        print(f"  [ERROR] Failed to download M15 data for {symbol}: {mt5.last_error()}")
    else:
        df_m15 = pd.DataFrame(rates_m15)
        df_m15['time'] = pd.to_datetime(df_m15['time'], unit='s')
        out_m15 = Path("data/historical") / f"{symbol}_M15.csv"
        df_m15.to_csv(out_m15, index=False)
        print(f"  [SUCCESS] Exported M15: {len(df_m15):,} bars to {out_m15}")

def main():
    print("Starting historical data export...")
    if not mt5_conn.connect():
        print("[ERROR] Cannot connect to MT5. Exiting.")
        sys.exit(1)
        
    try:
        # Create output directory
        Path("data/historical").mkdir(parents=True, exist_ok=True)
        for sym in SYMBOLS:
            export_symbol_history(sym)
    finally:
        mt5_conn.disconnect()
        print("\nFinished.")

if __name__ == "__main__":
    main()
