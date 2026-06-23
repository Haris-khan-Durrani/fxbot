import MetaTrader5 as mt5
from dotenv import load_dotenv
import os

load_dotenv()

login = int(os.environ.get("MT5_LOGIN", 0))
password = os.environ.get("MT5_PASSWORD", "")
server = os.environ.get("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    # Try without credentials
    if not mt5.initialize():
        print("MT5 Init without credentials failed:", mt5.last_error())
        exit(1)

print("MT5 Connected.")

# Check open positions
positions = mt5.positions_get()
print("\n--- OPEN POSITIONS ---")
if positions:
    for pos in positions:
        print(f"Ticket: {pos.ticket}, Symbol: {pos.symbol}, Type: {pos.type}, Volume: {pos.volume}, Price Open: {pos.price_open}, SL: {pos.sl}, TP: {pos.tp}")
else:
    print("No open positions found.")

# Check symbol info
symbols = ["EURUSD", "GBPUSD", "XAUUSD", "NZDUSD"]
print("\n--- SYMBOL SPECIFICATIONS ---")
for symbol in symbols:
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"Symbol {symbol} not found")
        continue
    
    # Ensure selected
    if not info.visible:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
        
    print(f"\nSymbol: {symbol}")
    print(f"  Digits: {info.digits}")
    print(f"  Point: {info.point}")
    print(f"  Trade Contract Size: {info.trade_contract_size}")
    print(f"  Volume Min: {info.volume_min}")
    print(f"  Volume Max: {info.volume_max}")
    print(f"  Volume Step: {info.volume_step}")
    print(f"  Trade Tick Value: {info.trade_tick_value}")
    print(f"  Trade Tick Size: {info.trade_tick_size}")
    # Calculate pip value like in symbol_info.py
    pips_per_point = 10
    pip_value = info.trade_tick_value * pips_per_point
    print(f"  Calculated Pip Value: {pip_value}")

mt5.shutdown()
