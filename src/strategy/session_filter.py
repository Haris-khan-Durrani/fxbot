"""
src/strategy/session_filter.py
──────────────────────────────
Session filter: London and New York session detection.
Derives session windows from broker SERVER TIME via MT5 tick timestamps.
No hardcoded UTC offsets — fully broker-timezone-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)


class SessionLabel(str, Enum):
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    OVERLAP = "OVERLAP"     # London + NY both active
    OFF = "OFF"             # Outside all active sessions


@dataclass
class SessionResult:
    in_session: bool
    label: SessionLabel
    score: float    # 1.0 = overlap, 0.7 = single session, 0.0 = off


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' → (hour, minute)."""
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


def detect_session(server_timestamp: Optional[float] = None) -> SessionResult:
    """
    Determine which trading session is currently active.

    Args:
        server_timestamp: Unix timestamp from broker server (MT5 tick time).
                         If None, falls back to system UTC time.

    Returns:
        SessionResult with label and score.
    """
    london_open = get("strategy.session.london_open", "08:00")
    london_close = get("strategy.session.london_close", "17:00")
    ny_open = get("strategy.session.ny_open", "13:00")
    ny_close = get("strategy.session.ny_close", "22:00")

    if server_timestamp:
        now = datetime.fromtimestamp(server_timestamp, tz=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        log.debug("Session filter: no server timestamp, using system UTC time.")

    current_hour = now.hour
    current_minute = now.minute
    current_total = current_hour * 60 + current_minute

    def _to_minutes(time_str: str) -> int:
        h, m = _parse_time(time_str)
        return h * 60 + m

    london_start = _to_minutes(london_open)
    london_end = _to_minutes(london_close)
    ny_start = _to_minutes(ny_open)
    ny_end = _to_minutes(ny_close)

    in_london = london_start <= current_total < london_end
    in_ny = ny_start <= current_total < ny_end

    if in_london and in_ny:
        label = SessionLabel.OVERLAP
        score = 1.0
        in_session = True
    elif in_london:
        label = SessionLabel.LONDON
        score = 0.7
        in_session = True
    elif in_ny:
        label = SessionLabel.NEW_YORK
        score = 0.7
        in_session = True
    else:
        label = SessionLabel.OFF
        score = 0.0
        in_session = False

    log.debug("Session: %s (score=%.1f)  server_time=%s",
              label.value, score, now.strftime("%H:%M UTC"))
    return SessionResult(in_session=in_session, label=label, score=score)


def session_score(result: SessionResult) -> float:
    """Return 0-1 score. Off-session = 0, single = 0.7, overlap = 1.0."""
    return result.score
