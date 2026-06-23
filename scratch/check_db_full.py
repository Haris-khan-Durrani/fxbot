from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import DailyStat, TradeHistory, Trade

load_dotenv()

from src.db.repository import session_scope

with session_scope() as s:
    print("--- ALL DAILY STATS ---")
    stats = s.query(DailyStat).all()
    for st in stats:
        print(f"Date: {st.date}, Opened: {st.trades_opened}, Closed: {st.trades_closed}, Wins: {st.wins}, Losses: {st.losses}, PnL: {st.pnl_usd}")

    print("\n--- ALL TRADE HISTORY ---")
    history = s.query(TradeHistory).all()
    for h in history:
        print(f"Ticket: {h.mt5_ticket}, Symbol: {h.symbol}, Direction: {h.direction}, Lots: {h.lot_size}, Open: {h.open_price}, Close: {h.close_price}, PnL: {h.pnl_usd}, Pips: {h.pips}, Opened: {h.opened_at}, Closed: {h.closed_at}")
