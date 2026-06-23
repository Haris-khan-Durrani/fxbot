import MetaTrader5 as mt5
from dotenv import load_dotenv
import os

load_dotenv()

login = int(os.environ.get("MT5_LOGIN", 0))
password = os.environ.get("MT5_PASSWORD", "")
server = os.environ.get("MT5_SERVER", "")

mt5.initialize(login=login, password=password, server=server)

symbols = ["EURUSD", "GBPUSD", "XAUUSD", "NZDUSD"]
for sym in symbols:
    info = mt5.symbol_info(sym)
    if info:
        print(f"\n{sym}:")
        open_price = info.ask if info.ask > 0 else info.bid
        pip_size = info.point * 10
        pip_value_calc = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, open_price, open_price + pip_size)
        print(f"  Live ask price: {open_price}")
        print(f"  Point: {info.point}")
        print(f"  Pip size (10 points): {pip_size:.5f}")
        print(f"  Order Calc Profit for 1 pip change: {pip_value_calc} USD")
        print(f"  MT5 Tick Value * 10: {info.trade_tick_value * 10}")

mt5.shutdown()
