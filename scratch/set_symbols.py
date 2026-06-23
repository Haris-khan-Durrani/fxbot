import sys
sys.path.insert(0, '.')
from src.core.config import load_config
load_config()
from src.db.init_db import init_database
init_database()
from src.db import repository as repo

# Update DB symbol list to only the two validated pairs
old = repo.get_setting("symbols", "")
print("Old symbols:", old)

repo.set_setting("symbols", "XAUUSD,GBPUSD")
new = repo.get_setting("symbols", "")
print("New symbols:", new)
print("Done. Bot will only scan XAUUSD and GBPUSD.")
