import sys

# Set standard output encoding to utf-8 or replace errors
sys.stdout.reconfigure(encoding='utf-8')

with open("logs/fxbot.log", "r", encoding="utf-8") as f:
    for i, line in enumerate(f, 1):
        if "57117263144" in line or "57116715909" in line:
            print(f"Line {i}: {line.strip()}")
