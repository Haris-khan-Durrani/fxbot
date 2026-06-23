"""
src/core/config.py
─────────────────
Singleton config loader. Reads config.yaml + .env, merges values,
validates required keys on startup. Raises ConfigError with clear messages.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


_REQUIRED_ENV_KEYS = [
    "MYSQL_HOST",
    "MYSQL_DB",
    "MYSQL_USER",
]

# MT5 credentials — only validated when MT5 is actually used
_MT5_ENV_KEYS = [
    "MT5_LOGIN",
    "MT5_PASSWORD",
    "MT5_SERVER",
]

_OPTIONAL_ENV_KEYS = [
    "MT5_PATH",
    "MYSQL_PORT",
    "MYSQL_PASSWORD",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_PROXY_URL",
    "LIVE_TRADING_ENABLED",
]


@lru_cache(maxsize=1)
def load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load and merge config.yaml + .env into a single config dict.
    Called once; result is cached for the process lifetime.
    """
    # Locate project root (two levels up from this file)
    project_root = Path(__file__).resolve().parents[2]

    # Load .env
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()  # fall back to system env

    # Load config.yaml
    yaml_file = Path(config_path) if config_path else project_root / "config.yaml"
    if not yaml_file.exists():
        raise ConfigError(f"config.yaml not found at {yaml_file}")

    with yaml_file.open("r", encoding="utf-8") as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    # Inject env vars into cfg["env"]
    cfg["env"] = {}
    for key in _REQUIRED_ENV_KEYS + _MT5_ENV_KEYS + _OPTIONAL_ENV_KEYS:
        cfg["env"][key] = os.environ.get(key, "")

    # Validate always-required env vars
    missing = [k for k in _REQUIRED_ENV_KEYS if not cfg["env"][k]]
    if missing:
        raise ConfigError(
            f"Missing required environment variables: {missing}\n"
            "Copy .env.example → .env and fill in your credentials."
        )

    # Validate live trading safety flag
    live_env = cfg["env"].get("LIVE_TRADING_ENABLED", "false").lower()
    live_yaml = str(cfg.get("trading", {}).get("live_trading_enabled", False)).lower()
    cfg["_live_trading_enabled"] = (live_env == "true") and (live_yaml == "true")

    return cfg


def get(path: str, default: Any = None) -> Any:
    """
    Dot-notation accessor for nested config values.
    E.g. get("strategy.trend.ema_fast") → 50
    """
    cfg = load_config()
    keys = path.split(".")
    node: Any = cfg
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key, default)
        else:
            return default
    return node if node is not None else default


def is_live_trading_enabled() -> bool:
    """Returns True only if BOTH config.yaml AND .env explicitly enable live trading."""
    return load_config().get("_live_trading_enabled", False)


def mysql_url() -> str:
    """Returns the SQLAlchemy MySQL connection URL."""
    cfg = load_config()
    env = cfg["env"]
    host = env.get("MYSQL_HOST", "localhost")
    port = env.get("MYSQL_PORT", "3306") or "3306"
    db = env["MYSQL_DB"]
    user = env["MYSQL_USER"]
    password = env["MYSQL_PASSWORD"]
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"


if __name__ == "__main__":
    # Quick sanity test: python -m src.core.config
    import json
    cfg = load_config()
    # Redact secrets before printing
    display = {k: v for k, v in cfg.items() if k not in ("env",)}
    display["env"] = {k: ("***" if "PASSWORD" in k or "TOKEN" in k else v) for k, v in cfg["env"].items()}
    print(json.dumps(display, indent=2, default=str))
    print(f"\n✅ Config loaded. Live trading enabled: {is_live_trading_enabled()}")
