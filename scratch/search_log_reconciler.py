import sys
sys.stdout.reconfigure(encoding='utf-8')

with open("logs/fxbot.log", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "Dynamic sync" in line or "Reconciliation" in line or "reconcile" in line.lower() or "sync_closed_deals" in line:
            print(f"Line {i}: {line.strip()}")
