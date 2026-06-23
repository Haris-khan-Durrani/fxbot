"""
scripts/generate_dummy_data.py
──────────────────────────────
Generate realistic synthetic data for backtest verification.
Generates M15 and resamples to H1 for XAUUSD, EURUSD, GBPUSD.
"""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import pandas as pd

def generate_symbol_data(
    symbol: str,
    start_price: float,
    volatility: float,
    num_days: int = 180,
) -> None:
    # 5 days a week, 24 hours a day, 4 bars per hour = 480 bars/day
    freq = "15min"
    periods = num_days * 24 * 4
    
    # Generate timezone-naive UTC timestamps (matching standard format)
    idx = pd.date_range("2024-01-01 00:00:00", periods=periods, freq=freq)
    
    # Exclude weekends (forex is Mon-Fri)
    idx = idx[idx.dayofweek < 5]
    
    n = len(idx)
    
    # Simple random walk for log-returns
    np.random.seed(42 + hash(symbol) % 1000)
    returns = np.random.normal(loc=0.0, scale=volatility, size=n)
    
    # Add a slight upward drift to make it realistic
    drift = 0.00002
    price_path = start_price * np.exp(np.cumsum(returns + drift))
    
    # Generate OHLC
    df_m15 = pd.DataFrame(index=idx)
    df_m15["close"] = price_path
    
    # Add noise to get open, high, low
    noise_range = start_price * volatility * 0.5
    df_m15["open"] = df_m15["close"].shift(1).fillna(start_price)
    
    # Make high the max of open, close + positive noise
    high_noise = np.random.exponential(scale=noise_range, size=n)
    df_m15["high"] = np.maximum(df_m15["open"], df_m15["close"]) + high_noise
    
    # Make low the min of open, close - positive noise
    low_noise = np.random.exponential(scale=noise_range, size=n)
    df_m15["low"] = np.minimum(df_m15["open"], df_m15["close"]) - low_noise
    
    # Add volume
    df_m15["tick_volume"] = np.random.poisson(lam=500, size=n)
    
    df_m15.index.name = "time"
    
    # Reset index so "time" is a column in CSV, matching expected format
    df_m15_csv = df_m15.reset_index()
    # Format time column to standard string format
    df_m15_csv["time"] = df_m15_csv["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Resample to H1
    df_h1 = df_m15.resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "tick_volume": "sum",
    }).dropna()
    
    df_h1_csv = df_h1.reset_index()
    df_h1_csv["time"] = df_h1_csv["time"].dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Save files
    out_dir = Path(__file__).resolve().parents[1] / "data" / "historical"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    m15_path = out_dir / f"{symbol}_M15.csv"
    h1_path = out_dir / f"{symbol}_H1.csv"
    
    df_m15_csv.to_csv(m15_path, index=False)
    df_h1_csv.to_csv(h1_path, index=False)
    
    print(f"Generated {symbol}:")
    print(f"  M15 -> {m15_path} ({len(df_m15)} rows)")
    print(f"  H1  -> {h1_path} ({len(df_h1)} rows)")

def main():
    # Volatilities: EURUSD (very low), GBPUSD (low), XAUUSD (medium)
    generate_symbol_data("EURUSD", start_price=1.0850, volatility=0.0003)
    generate_symbol_data("GBPUSD", start_price=1.2650, volatility=0.0004)
    generate_symbol_data("XAUUSD", start_price=2030.0, volatility=0.0008)
    print("\nAll historical dummy data files created! ✅")

if __name__ == "__main__":
    main()
