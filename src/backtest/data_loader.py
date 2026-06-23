"""
src/backtest/data_loader.py
───────────────────────────
Load historical OHLCV data from CSV files.
No MT5 dependency — pure pandas.

Supported CSV format (e.g., from Dukascopy or MT5 export):
    Date,Time,Open,High,Low,Close,Volume
    2022.01.03,00:00,1824.50,1830.00,1820.10,1827.30,1234
OR standard format:
    time,open,high,low,close,tick_volume,spread,real_volume
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from src.core.logger import get_logger

log = get_logger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "historical"


def load_csv(
    symbol: str,
    timeframe: str,
    filepath: Optional[Path] = None,
) -> pd.DataFrame:
    """
    Load historical OHLCV data from a CSV file.

    Auto-detects two common formats:
      1. MT5 export: Date,Time,Open,High,Low,Close,Volume
      2. Standard:   time,open,high,low,close,tick_volume,spread

    Args:
        symbol:    E.g. "XAUUSD"
        timeframe: E.g. "M15"
        filepath:  Explicit path. If None, looks in data/historical/{symbol}_{timeframe}.csv

    Returns:
        DataFrame with DatetimeIndex (UTC) and columns: open, high, low, close, volume
    """
    if filepath is None:
        filepath = _DATA_DIR / f"{symbol}_{timeframe}.csv"

    if not filepath.exists():
        raise FileNotFoundError(
            f"Historical data not found: {filepath}\n"
            f"Export M15/H1 history from MT5: File → Open Data Folder → History, "
            f"or download from Dukascopy/TrueFX and save as {symbol}_{timeframe}.csv"
        )

    log.info("Loading historical data: %s", filepath)

    # Try to detect format by reading first row
    df_peek = pd.read_csv(filepath, nrows=2)
    cols = [c.lower().strip() for c in df_peek.columns]

    if "date" in cols and "time" in cols:
        # MT5 export format
        df = _load_mt5_format(filepath)
    elif "time" in cols or "<date>" in cols:
        df = _load_standard_format(filepath)
    else:
        raise ValueError(
            f"Unrecognized CSV format in {filepath}. "
            "Expected columns: Date,Time,Open,High,Low,Close,Volume "
            "or time,open,high,low,close,tick_volume"
        )

    df = df.sort_index()
    log.info("Loaded %d rows for %s %s  [%s → %s]",
             len(df), symbol, timeframe,
             df.index[0].strftime("%Y-%m-%d"),
             df.index[-1].strftime("%Y-%m-%d"))
    return df


def _load_mt5_format(filepath: Path) -> pd.DataFrame:
    """Parse MT5 Date+Time columns into DatetimeIndex."""
    df = pd.read_csv(filepath, sep="\t" if "\t" in filepath.read_text()[:100] else ",")
    # Normalize column names
    df.columns = [c.lower().strip().lstrip("<").rstrip(">") for c in df.columns]

    if "date" in df.columns and "time" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"].astype(str) + " " + df["time"].astype(str))
    elif "date" in df.columns:
        df["datetime"] = pd.to_datetime(df["date"])
    else:
        df["datetime"] = pd.to_datetime(df.index)

    df = df.set_index("datetime")
    df.index = df.index.tz_localize("UTC")

    rename = {"open": "open", "high": "high", "low": "low", "close": "close",
               "vol": "volume", "volume": "volume", "tickvol": "volume",
               "tick_volume": "volume"}
    df = df.rename(columns={c: rename.get(c, c) for c in df.columns})

    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "close"])


def _load_standard_format(filepath: Path) -> pd.DataFrame:
    """Parse standard time,open,high,low,close format."""
    df = pd.read_csv(filepath)
    df.columns = [c.lower().strip().lstrip("<").rstrip(">") for c in df.columns]

    time_col = next((c for c in df.columns if "time" in c or "date" in c), None)
    if time_col is None:
        raise ValueError("Cannot find time column in CSV.")

    df["datetime"] = pd.to_datetime(df[time_col], utc=True)
    df = df.set_index("datetime").drop(columns=[time_col], errors="ignore")

    rename = {"tickvol": "volume", "tick_volume": "volume", "vol": "volume"}
    df = df.rename(columns=rename)

    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].apply(pd.to_numeric, errors="coerce").dropna(subset=["open", "close"])
