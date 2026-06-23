import pandas as pd
from pathlib import Path

data_dir = Path("data/historical")
for p in data_dir.glob("*_M15.csv"):
    df = pd.read_csv(p)
    # Print start and end dates
    print(f"File: {p.name}")
    print(f"  Rows: {len(df)}")
    print(f"  First row: {df.iloc[0].to_dict()}")
    print(f"  Last row: {df.iloc[-1].to_dict()}")
