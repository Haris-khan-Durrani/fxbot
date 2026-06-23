import pandas as pd
from pathlib import Path

csv_path = Path("data/historical/sweep_results_aud_nzd.csv")
if csv_path.exists():
    df = pd.read_csv(csv_path)
    
    # Replace emojis for console printing
    df["Pass Gate"] = df["Pass Gate"].str.replace("✅", "PASS").str.replace("❌", "FAIL")
    
    print("=== AUDUSD SWEEP RESULTS ===")
    aud = df[df["Symbol"] == "AUDUSD"]
    print(aud.to_string(index=False))
    
    print("\n=== NZDUSD SWEEP RESULTS ===")
    nzd = df[df["Symbol"] == "NZDUSD"]
    print(nzd.to_string(index=False))
    
    # Check if any configuration passed the gate
    passing = df[df["Pass Gate"] == "PASS"]
    print("\n=== PASSING CONFIGURATIONS ===")
    if len(passing) > 0:
        print(passing.to_string(index=False))
    else:
        print("No configurations passed the gate for AUDUSD or NZDUSD!")
else:
    print("CSV file not found!")
