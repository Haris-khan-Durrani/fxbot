"""
src/core/logger.py
──────────────────
Structured logging: rotating file handler (daily) + coloured console.
Call get_logger(__name__) in every module.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_FMT = "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_LEVEL_COLORS = {
    "DEBUG":    "\033[36m",   # cyan
    "INFO":     "\033[32m",   # green
    "WARNING":  "\033[33m",   # yellow
    "ERROR":    "\033[31m",   # red
    "CRITICAL": "\033[35m",   # magenta
}
_RESET = "\033[0m"


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        color = _LEVEL_COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{_RESET}"
        return super().format(record)


def _get_log_level() -> int:
    """Read log level from env or default to INFO."""
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level_str, logging.INFO)


def setup_root_logger() -> None:
    """Configure the root logger. Call once at startup (main.py)."""
    root = logging.getLogger()
    if root.handlers:
        return  # Already configured

    level = _get_log_level()
    root.setLevel(level)

    # ── Console handler (coloured) ─────────────────────────────────
    # Reconfigure stdout to UTF-8 on Windows (avoids CP1252 emoji crashes)
    import sys, io
    if hasattr(sys.stdout, 'buffer'):
        utf8_stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True
        )
    else:
        utf8_stdout = sys.stdout

    console = logging.StreamHandler(utf8_stdout)
    console.setLevel(level)
    console.setFormatter(_ColorFormatter(fmt=_FMT, datefmt=_DATE_FMT))
    root.addHandler(console)

    # ── File handler (daily rotation, keep 30 days) ────────────────
    log_file = _LOG_DIR / "fxbot.log"
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(fmt=_FMT, datefmt=_DATE_FMT))
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call setup_root_logger() first in main.py."""
    return logging.getLogger(name)
