import MetaTrader5 as mt5
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta

load_dotenv()

login = int(os.environ.get("MT5_LOGIN", 0))
password = os.environ.get("MT5_PASSWORD", "")
server = os.environ.get("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 init failed")
    exit(1)

print("MT5 Connected.")

start_time = datetime.now() - timedelta(days=1)
end_time = datetime.now() + timedelta(days=1)

deals = mt5.history_deals_get(start_time, end_time)
if deals:
    print(f"\nFound {len(deals)} deals in MT5 history.")
    for d in deals:
        # Check if DEAL_ENTRY_OUT (closing deal)
        is_close = "OUT" if d.entry == mt5.DEAL_ENTRY_OUT else ("IN" if d.entry == mt5.DEAL_ENTRY_IN else "OTHER")
        print(f"Ticket/PosID: {d.position_id}, Symbol: {d.symbol}, Type: {d.type}, Entry: {is_close}, Volume: {d.volume}, Profit: {d.profit}, Swap: {d.swap}, Comm: {d.commission}, Time: {datetime.fromtimestamp(d.time)}")
else:
    print("No deals found in MT5 history.")

mt5.shutdown()
