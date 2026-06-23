"""
src/data/mt5_connection.py
──────────────────────────
MT5 connection manager with auto-reconnect and exponential backoff.
On Linux, this connects to the MT5 terminal running inside Wine.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from src.core.config import load_config
from src.core.logger import get_logger

log = get_logger(__name__)

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    log.warning("MetaTrader5 package not installed. Running in SIMULATION mode.")
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

_CONNECTED: bool = False
_MAX_RETRIES = 10
_BASE_DELAY = 2.0   # seconds
_MAX_DELAY = 120.0  # seconds


def connect(max_retries: int = _MAX_RETRIES) -> bool:
    """
    Initialize connection to the MT5 terminal.
    Retries with exponential backoff up to max_retries times.
    Returns True on success, False if all retries exhausted.
    """
    global _CONNECTED

    if not MT5_AVAILABLE:
        log.warning("MT5 package unavailable — cannot connect.")
        return False

    cfg = load_config()

    # Validate MT5 credentials at connection time
    mt5_login = cfg["env"].get("MT5_LOGIN", "")
    mt5_password = cfg["env"].get("MT5_PASSWORD", "")
    if not mt5_login or not mt5_password:
        log.error(
            "MT5 credentials not set. Please fill MT5_LOGIN and MT5_PASSWORD in your .env file."
        )
        return False

    login = int(mt5_login)
    password = mt5_password
    server = cfg["env"]["MT5_SERVER"]
    mt5_path = cfg["env"].get("MT5_PATH") or None

    # First, try to connect without credentials to leverage the already running terminal session
    try:
        init_args = {"path": mt5_path} if mt5_path else {}
        if mt5.initialize(**init_args):
            info = mt5.account_info()
            if info and info.login == login:
                _CONNECTED = True
                log.info("✅ MT5 connected via active terminal | Account: %d | Balance: %.2f %s | Demo: %s",
                         info.login, info.balance, info.currency,
                         "YES" if info.trade_mode == 0 else "NO")
                _assert_demo_mode(info)
                return True
            mt5.shutdown()
    except Exception as e:
        log.debug("Fallback terminal check failed: %s", e)

    delay = _BASE_DELAY
    for attempt in range(1, max_retries + 1):
        log.info("MT5 connect attempt %d/%d (server=%s login=%d) ...",
                 attempt, max_retries, server, login)

        init_kwargs: dict = {"login": login, "password": password, "server": server}
        if mt5_path:
            init_kwargs["path"] = mt5_path

        if mt5.initialize(**init_kwargs):
            info = mt5.account_info()
            if info is None:
                log.error("MT5 initialized but account_info() returned None.")
                mt5.shutdown()
            else:
                _CONNECTED = True
                log.info("✅ MT5 connected | Account: %d | Balance: %.2f %s | Demo: %s",
                         info.login, info.balance, info.currency,
                         "YES" if info.trade_mode == 0 else "NO")
                _assert_demo_mode(info)
                return True

        error = mt5.last_error()
        log.warning("MT5 connect failed (attempt %d): %s | Retrying in %.0fs ...",
                    attempt, error, delay)
        time.sleep(delay)
        delay = min(delay * 2, _MAX_DELAY)

    log.error("MT5 connection failed after %d attempts.", max_retries)
    _CONNECTED = False
    return False


def _assert_demo_mode(account_info) -> None:
    """Hard-crash if account is live and demo_only_assert is true in config."""
    from src.core.config import get
    if get("trading.demo_only_assert", True):
        # trade_mode: 0 = demo, 1 = contest, 2 = real
        if account_info.trade_mode != 0:
            raise RuntimeError(
                f"⛔ SAFETY VIOLATION: Connected to a LIVE account (trade_mode={account_info.trade_mode}) "
                "but demo_only_assert=true in config.yaml. Shutting down."
            )


def disconnect() -> None:
    """Shutdown MT5 connection."""
    global _CONNECTED
    if MT5_AVAILABLE:
        mt5.shutdown()
    _CONNECTED = False
    log.info("MT5 disconnected.")


def is_connected() -> bool:
    """Return True if MT5 is connected and responsive."""
    if not MT5_AVAILABLE or not _CONNECTED:
        return False
    # A quick API call to verify the terminal is still alive
    return mt5.terminal_info() is not None


def ensure_connected() -> bool:
    """Check connection; reconnect if lost. Returns True if connected."""
    if is_connected():
        return True
    log.warning("MT5 connection lost — attempting reconnect ...")
    from src.db.repository import log_system_event
    log_system_event("WARNING", "MT5_RECONNECT", "MT5 connection lost, attempting reconnect.")
    return connect()


class MT5Session:
    """Context manager: connect on enter, disconnect on exit."""
    def __enter__(self):
        if not connect():
            raise ConnectionError("Failed to connect to MT5 terminal.")
        return self

    def __exit__(self, *args):
        disconnect()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2]))
    from src.core.logger import setup_root_logger
    setup_root_logger()
    success = connect()
    print(f"\n{'✅ Connected' if success else '❌ Connection failed'}")
    if success:
        disconnect()
