import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.data.mt5_connection import connect, disconnect, is_connected
from src.data.candles import get_candles
from src.strategy.trend import detect_trend, TrendDirection, calc_ema
from src.strategy.structure import detect_bos, _find_swing_high, _find_swing_low
from src.strategy.liquidity import detect_liquidity_sweep
from src.strategy.momentum import detect_momentum, calc_rsi
from src.strategy.session_filter import detect_session
from src.scoring.engine import score_signal
from src.data.account_info import get_server_time

def main():
    if not connect(max_retries=3):
        return
        
    try:
        server_ts = get_server_time()
        session = detect_session(server_ts)
        print("--- Session Status ---")
        print(f"Server Time: {server_ts}")
        print(f"In session: {session.in_session} | Label: {session.label}")
        
        for symbol in ["GBPUSD", "XAUUSD"]:
            print(f"\n==========================================")
            print(f"        DIAGNOSTICS FOR {symbol}          ")
            print(f"==========================================")
            
            # Fetch fresh (non-cached)
            df_h1 = get_candles(symbol, "H1", count=300, validate=False)
            df_m15 = get_candles(symbol, "M15", count=200, validate=False)
            
            # 1. Trend (H1)
            trend = detect_trend(df_h1)
            close_h1 = df_h1["close"]
            ema_fast = calc_ema(close_h1, 50).iloc[-1]
            ema_slow = calc_ema(close_h1, 200).iloc[-1]
            print(f"1. Trend (H1): {trend.value}")
            print(f"   - Close: {close_h1.iloc[-1]:.5f}")
            print(f"   - EMA 50: {ema_fast:.5f} | EMA 200: {ema_slow:.5f}")
            
            # 2. Structure (M15)
            bos = detect_bos(df_m15)
            sw_high = _find_swing_high(df_m15, 20, 2)
            sw_low = _find_swing_low(df_m15, 20, 2)
            print(f"2. Structure (M15): {bos.direction.value} (conf={bos.confidence:.2f}, level={bos.break_level})")
            print(f"   - Recent closes: {list(df_m15['close'].iloc[-3:])}")
            print(f"   - Swing High: {sw_high} | Swing Low: {sw_low}")
            
            # 3. Liquidity Sweep (M15)
            sweep = detect_liquidity_sweep(df_m15)
            print(f"3. Liquidity Sweep (M15): Detected={sweep.detected} | Dir={sweep.direction}")
            
            # 4. Momentum (M15)
            mom = detect_momentum(df_m15)
            rsi_val = float(calc_rsi(df_m15["close"], 14).iloc[-1])
            print(f"4. Momentum (M15): State={mom.state.value} | RSI={rsi_val:.2f}")
            
            # 5. Score Breakdown
            breakdown = score_signal(symbol, trend, bos, sweep, mom, session)
            print(f"\nFinal Score: {breakdown.total}")
            print(f"Components: Trend={breakdown.trend}, Struct={breakdown.structure}, Liq={breakdown.liquidity}, Mom={breakdown.momentum}, Sess={breakdown.session}")
            print(f"Passed Threshold: {breakdown.passed} (Reason: {breakdown.skip_reason})")
            
    finally:
        disconnect()

if __name__ == "__main__":
    main()
