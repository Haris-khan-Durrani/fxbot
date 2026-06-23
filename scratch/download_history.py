import sys
import os
from datetime import datetime, timezone
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5
from src.data.mt5_connection import connect, is_connected

def download_and_save(symbol, timeframe_str, mt5_timeframe, start_dt, end_dt):
    print(f"Downloading {symbol} {timeframe_str}...")
    rates = mt5.copy_rates_range(symbol, mt5_timeframe, start_dt, end_dt)
    if rates is None or len(rates) == 0:
        print(f"Error copying rates for {symbol} {timeframe_str}: {mt5.last_error()}")
        return False
    
    df = pd.DataFrame(rates)
    # Convert time to formatted string
    df['time'] = pd.to_datetime(df['time'], unit='s').dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Select and rename columns to match existing format:
    # time,open,high,low,close,tick_volume,spread,real_volume
    cols = ['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread', 'real_volume']
    # Make sure all columns exist
    for c in cols:
        if c not in df.columns:
            df[c] = 0
            
    df = df[cols]
    
    out_path = f"data/historical/{symbol}_{timeframe_str}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")
    return True

def main():
    if not is_connected():
        connect()
    
    if not is_connected():
        print("MT5 not connected")
        sys.exit(1)
        
    start_dt = datetime(2024, 1, 2, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 17, tzinfo=timezone.utc)
    
    for symbol in ["AUDUSD", "NZDUSD"]:
        # Select symbol in MT5 first
        if not mt5.symbol_select(symbol, True):
            print(f"Failed to select {symbol}")
            continue
            
        download_and_save(symbol, "M15", mt5.TIMEFRAME_M15, start_dt, end_dt)
        download_and_save(symbol, "H1", mt5.TIMEFRAME_H1, start_dt, end_dt)

if __name__ == "__main__":
    main()
