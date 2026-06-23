"""Concrete test case verification for RSI and BOS ATR gate."""
import sys
import pandas as pd
import numpy as np

# Ensure sys.path is correct
sys.path.insert(0, r'c:\Users\Muneeb\Documents\fxbot')

from src.strategy.momentum import momentum_score, MomentumResult, MomentumState
from src.backtest.strategy_functions import detect_bos_bar, calc_atr

print("=" * 65)
print("1. RSI DIRECTION-AWARE SCORING -- 8 concrete cases")
print("=" * 65)
cases = [
    ("RSI=72 + BUY  (overbought -> 0.3, not 0.0)",  MomentumResult(72.0, MomentumState.OVERBOUGHT),      "BUY",  0.3),
    ("RSI=65 + BUY  (bull-neutral 50-70 -> 0.8)",   MomentumResult(65.0, MomentumState.BULLISH_NEUTRAL), "BUY",  0.8),
    ("RSI=35 + BUY  (bear-neutral 30-50 -> 0.5)",   MomentumResult(35.0, MomentumState.BEARISH_NEUTRAL), "BUY",  0.5),
    ("RSI=25 + BUY  (oversold -> 1.0)",              MomentumResult(25.0, MomentumState.OVERSOLD),        "BUY",  1.0),
    ("RSI=72 + SELL (overbought -> 1.0)",            MomentumResult(72.0, MomentumState.OVERBOUGHT),      "SELL", 1.0),
    ("RSI=35 + SELL (bear-neutral 30-50 -> 0.8)",   MomentumResult(35.0, MomentumState.BEARISH_NEUTRAL), "SELL", 0.8),
    ("RSI=65 + SELL (bull-neutral 50-70 -> 0.5)",   MomentumResult(65.0, MomentumState.BULLISH_NEUTRAL), "SELL", 0.5),
    ("RSI=25 + SELL (oversold -> 0.3, not 0.0)",    MomentumResult(25.0, MomentumState.OVERSOLD),        "SELL", 0.3),
]
all_rsi_ok = True
for label, result, direction, expected in cases:
    got = momentum_score(result, direction)
    ok = abs(got - expected) < 1e-9
    all_rsi_ok = all_rsi_ok and ok
    status = "OK" if ok else f"FAIL (expected {expected})"
    print(f"  {label}")
    print(f"    got={got:.1f}  [{status}]")

print()
print("=" * 65)
print("2. BOS ATR GATE -- 4 concrete cases")
print("=" * 65)

def make_flat_df(n, base, candle_range, break_above):
    """flat market + last 2 bars close `break_above` above swing high."""
    half = candle_range / 2
    idx = pd.date_range("2023-01-01", periods=n, freq="15min", tz="UTC")
    closes = [base] * n
    highs  = [base + half] * n
    lows   = [base - half] * n
    for i in [-2, -1]:
        closes[i] = base + half + break_above
        # Let's keep high/low of breakout candles same as range to not inflate ATR
        highs[i]  = base + half + break_above
        lows[i]   = base - half + break_above
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows, "close": closes,
    }, index=idx)

candle_range = 0.0020   # 20-pip candle range -> ATR ~ 0.0020
# min_break = 0.10 * 0.002 = 0.0002

tests = [
    ("Break = 0.04xATR = 0.00008 (BELOW threshold)", candle_range, 0.00008, "NONE"),
    ("Break = 0.08xATR = 0.00016 (BELOW threshold)", candle_range, 0.00016, "NONE"),
    ("Break = 0.10xATR = 0.00020 (AT threshold)",    candle_range, 0.00020, "BULLISH"),
    ("Break = 0.50xATR = 0.00100 (ABOVE threshold)", candle_range, 0.00100, "BULLISH"),
]

all_bos_ok = True
for label, cr, brk, expected in tests:
    df = make_flat_df(100, 1.3000, cr, brk)
    # Debug info
    swing_high = df["high"].iloc[-22:-2].max()
    atr = calc_atr(df, 14).iloc[-1]
    min_break = atr * 0.10
    break_dist = df["close"].iloc[-1] - swing_high
    
    direction, conf = detect_bos_bar(df, lookback=20, confirm=2, min_break_atr_ratio=0.10)
    ok = direction == expected
    all_bos_ok = all_bos_ok and ok
    status = "OK" if ok else f"FAIL (expected {expected})"
    print(f"  {label}")
    print(f"    swing_high={swing_high:.5f}, close={df['close'].iloc[-1]:.5f}")
    print(f"    atr={atr:.5f}, min_break_req={min_break:.5f}, break_dist={break_dist:.5f}")
    print(f"    direction={direction}  conf={conf:.3f}  [{status}]")

print()
print("=" * 65)
print(f"SUMMARY: RSI={'ALL OK' if all_rsi_ok else 'FAILURES'}  |  BOS={'ALL OK' if all_bos_ok else 'FAILURES'}")
print("=" * 65)
