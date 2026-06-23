import sys
sys.path.insert(0, '.')
from src.core.config import load_config
load_config()
from src.db.init_db import init_database
init_database()
from src.db import repository as repo

estop = repo.is_emergency_stop()
print("Emergency stop active:", estop)

symbols = repo.get_setting("symbols", "NOT SET")
print("Active symbols in DB:", symbols)

pnl = repo.get_today_pnl()
print("Today P&L: $" + str(round(pnl, 2)))

open_trades = repo.count_open_trades()
print("Open trades in DB:", open_trades)

if estop:
    print("Clearing emergency stop for demo restart...")
    repo.reset_emergency_stop()
    print("Emergency stop cleared.")
else:
    print("No emergency stop — ready to launch.")
