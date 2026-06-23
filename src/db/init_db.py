"""
src/db/init_db.py
─────────────────
Create all MySQL tables. Safe to re-run (CREATE TABLE IF NOT EXISTS).
Usage:
    python -m src.db.init_db
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.logger import get_logger, setup_root_logger
from src.db.models import Base, Settings, get_engine, get_session

setup_root_logger()
log = get_logger(__name__)


def init_database() -> None:
    """Create all tables and seed default settings rows."""
    engine = get_engine()
    log.info("Connecting to MySQL at %s ...", engine.url.host)

    Base.metadata.create_all(engine)
    log.info("All tables created / verified ✅")

    # Seed essential settings keys
    with get_session() as session:
        _seed_setting(session, "emergency_stop", "false",
                      "Set to 'true' to halt all new orders immediately")
        _seed_setting(session, "bot_version", "1.0.0", "Current bot version")
        _seed_setting(session, "symbols", "XAUUSD,EURUSD,GBPUSD", "Comma-separated list of symbols to trade")
        session.commit()

    log.info("Default settings seeded ✅")


def _seed_setting(session, key: str, value: str, note: str = "") -> None:
    """Insert a settings row only if the key doesn't already exist."""
    from sqlalchemy import select
    existing = session.execute(
        select(Settings).where(Settings.key == key)
    ).scalar_one_or_none()
    if existing is None:
        session.add(Settings(key=key, value=value))
        log.debug("Seeded setting: %s = %s", key, value)


if __name__ == "__main__":
    try:
        init_database()
        print("\n✅ Database initialized successfully.")
    except Exception as e:
        print(f"\n❌ Database initialization failed: {e}")
        sys.exit(1)
