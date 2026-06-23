from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import Trade, TradeHistory

load_dotenv()

from src.db.repository import session_scope

with session_scope() as s:
    print("--- OPEN TRADES ---")
    trades = s.query(Trade).all()
    if not trades:
        print("No open trades found.")
    for t in trades:
        print(f"ID: {t.id}, Ticket: {t.mt5_ticket}, Symbol: {t.symbol}, Direction: {t.direction}, Lots: {t.lot_size}, Open: {t.open_price}, SL: {t.sl_price}, TP: {t.tp_price}, Status: {t.status}, Opened: {t.opened_at}")

    print("\n--- CLOSED TRADES HISTORY ---")
    history = s.query(TradeHistory).all()
    if not history:
        print("No closed trades found.")
    for h in history:
        print(f"ID: {h.id}, Ticket: {h.mt5_ticket}, Symbol: {h.symbol}, Direction: {h.direction}, Lots: {h.lot_size}, Open: {h.open_price}, Close: {h.close_price}, SL: {h.sl_price}, TP: {h.tp_price}, PnL: {h.pnl_usd}, Pips: {h.pips}, Opened: {h.opened_at}, Closed: {h.closed_at}")
