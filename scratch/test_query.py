from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.db.models import TradeHistory, DailyStat

load_dotenv()

from src.db.repository import session_scope

ticket = 57117263144

with session_scope() as s:
    res = s.query(TradeHistory).filter_by(mt5_ticket=ticket).first()
    print("Query result for ticket 57117263144:", res)
    if res:
        print(f"  Found row: ID={res.id}, mt5_ticket={res.mt5_ticket}, Symbol={res.symbol}, PnL={res.pnl_usd}")
    else:
        print("  Not found in TradeHistory!")
        
    # Let's print all TradeHistory rows and their mt5_ticket type
    print("\nAll TradeHistory rows:")
    rows = s.query(TradeHistory).all()
    for r in rows:
        print(f"  ID={r.id}, mt5_ticket={r.mt5_ticket} (type={type(r.mt5_ticket)}), PnL={r.pnl_usd}")
