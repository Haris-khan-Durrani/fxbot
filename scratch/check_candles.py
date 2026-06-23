import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.append(str(Path(__file__).parent.parent))

from src.data.mt5_connection import connect, disconnect, is_connected
import MetaTrader5 as mt5

def main():
    if not connect(max_retries=3):
        return
        
    try:
        print(f"MT5 Connected: {is_connected()}")
        print("\n--- Terminal Info ---")
        term_info = mt5.terminal_info()
        if term_info:
            print(f"  Connected to server: {term_info.connected}")
            print(f"  Trade allowed: {term_info.trade_allowed}")
            print(f"  Market watch count: {mt5.symbols_total()}")
            
        for symbol in ["GBPUSD", "XAUUSD"]:
            print(f"\n--- {symbol} Tick Info ---")
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                # tick.time is in seconds since epoch in broker time
                tick_dt = datetime.fromtimestamp(tick.time, tz=timezone.utc)
                print(f"  Tick time (broker/server epoch): {tick_dt}")
                print(f"  Bid: {tick.bid} | Ask: {tick.ask}")
                print(f"  Last: {tick.last} | Volume: {tick.volume}")
            else:
                print(f"  No tick info available for {symbol}. Last error: {mt5.last_error()}")
                
    finally:
        disconnect()

if __name__ == "__main__":
    main()
