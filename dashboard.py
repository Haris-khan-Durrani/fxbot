import uvicorn
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core.config import load_config
from src.core.logger import setup_root_logger

if __name__ == "__main__":
    setup_root_logger()
    load_config()
    print("Starting Web Dashboard at http://localhost:8000")
    uvicorn.run("src.web.api:app", host="0.0.0.0", port=8000, reload=True)
