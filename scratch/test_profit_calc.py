import MetaTrader5 as mt5
from dotenv import load_dotenv
import os

load_dotenv()

login = int(os.environ.get("MT5_LOGIN", 0))
password = os.environ.get("MT5_PASSWORD", "")
server = os.environ.get("MT5_SERVER", "")

mt5.initialize(login=login, password=password, server=server)

account_info = mt5.account_info()
print("Account Currency:", account_info.currency)
print("Account Balance:", account_info.balance)

symbols = ["EURUSD", "GBPUSD", "XAUUSD", "NZDUSD"]
for sym in symbols:
    info = mt5.symbol_info(sym)
    if info:
        print(f"\n{sym}:")
        print(f"  Point: {info.point}")
        print(f"  Digits: {info.digits}")
        print(f"  Tick Size: {info.trade_tick_size}")
        print(f"  Tick Value: {info.trade_tick_value}")
        print(f"  Contract Size: {info.trade_contract_size}")
        # Let's see how MT5 calculates profit for 1 lot with 100 points change
        # For buy, profit = (close - open) * contract_size * tick_value / tick_size ? Or what?
        # Let's check using mt5.order_calc_profit
        open_price = info.ask
        close_price_100_points = open_price + 100 * info.point
        profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, open_price, close_price_100_points)
        print(f"  1 Lot Buy Profit for +100 points (+{100*info.point:.5f}): {profit} USD")
        
        # Let's check with 10 pips change (assuming 1 pip = 10 points)
        close_price_10_pips = open_price + 10 * (info.point * 10)
        profit_10_pips = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, open_price, close_price_10_pips)
        print(f"  1 Lot Buy Profit for +10 pips: {profit_10_pips} USD")

mt5.shutdown()
