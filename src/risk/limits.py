"""
src/risk/limits.py
──────────────────
Enforce all trading limits before allowing a new trade:
  - Emergency stop flag
  - Max open trades globally
  - Max trades per day
  - Daily loss limit
  - Weekly loss limit
  - Spread filter
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from src.core.config import get
from src.core.logger import get_logger
from src.data.symbol_info import get_current_spread_pips
from src.db import repository as repo

log = get_logger(__name__)


@dataclass
class LimitCheckResult:
    allowed: bool
    reason: Optional[str] = None


def check_all_limits(symbol: str, balance: float) -> LimitCheckResult:
    """
    Run all limit checks before placing a new trade.
    Returns LimitCheckResult(allowed=False, reason=...) if any limit blocks the trade.
    """
    checks = [
        lambda: _check_symbol_validation(symbol),  # FIRST — hard block for unvalidated symbols
        _check_emergency_stop,
        lambda: _check_open_trades(),
        lambda: _check_daily_trade_count(),
        lambda: _check_daily_loss(balance),
        lambda: _check_weekly_loss(balance),
        lambda: _check_spread(symbol),
    ]

    for check in checks:
        result = check()
        if not result.allowed:
            log.warning("Trade BLOCKED: %s", result.reason)
            return result

    return LimitCheckResult(allowed=True)


def _check_symbol_validation(symbol: str) -> LimitCheckResult:
    """
    Hard block: symbol must appear in risk.validated_symbols config list.
    If the list is empty or not set, ALL symbols are blocked (fail-safe).
    Returns LimitCheckResult(allowed=False) — no order is placed, no exception raised.
    The scan loop in main.py treats any allowed=False result as "skip this symbol entirely".
    """
    validated: list[str] = get("risk.validated_symbols", [])
    if not validated:
        return LimitCheckResult(
            allowed=False,
            reason=f"{symbol} blocked — risk.validated_symbols is empty. Add symbols explicitly to config.yaml.",
        )
    if symbol not in validated:
        return LimitCheckResult(
            allowed=False,
            reason=f"{symbol} is NOT in risk.validated_symbols — backtest gate not passed. Trade blocked.",
        )
    return LimitCheckResult(allowed=True)


def _check_emergency_stop() -> LimitCheckResult:
    if repo.is_emergency_stop():
        return LimitCheckResult(
            allowed=False,
            reason="Emergency stop is active. Reset manually via DB before trading resumes.",
        )
    return LimitCheckResult(allowed=True)


def _check_open_trades() -> LimitCheckResult:
    max_trades = get("risk.max_open_trades", 1)
    current = repo.count_open_trades()
    if current >= max_trades:
        return LimitCheckResult(
            allowed=False,
            reason=f"Max open trades reached ({current}/{max_trades})",
        )
    return LimitCheckResult(allowed=True)


def _check_daily_trade_count() -> LimitCheckResult:
    max_daily = get("risk.max_trades_per_day", 2)
    today_count = repo.get_today_trade_count()
    if today_count >= max_daily:
        return LimitCheckResult(
            allowed=False,
            reason=f"Daily trade limit reached ({today_count}/{max_daily})",
        )
    return LimitCheckResult(allowed=True)


def _check_daily_loss(balance: float) -> LimitCheckResult:
    daily_limit_pct = get("risk.daily_loss_limit_pct", 3.0)
    today_pnl = repo.get_today_pnl()
    if today_pnl < 0:
        loss_pct = abs(today_pnl) / balance * 100
        if loss_pct >= daily_limit_pct:
            msg = (f"Daily loss limit hit ({loss_pct:.2f}% ≥ {daily_limit_pct}%). "
                   "No new trades today.")
            repo.log_system_event("WARNING", "DAILY_LOSS_LIMIT", msg)
            return LimitCheckResult(allowed=False, reason=msg)
    return LimitCheckResult(allowed=True)


def _check_weekly_loss(balance: float) -> LimitCheckResult:
    weekly_limit_pct = get("risk.weekly_loss_limit_pct", 8.0)
    weekly_pnl = _get_weekly_pnl()
    if weekly_pnl < 0:
        loss_pct = abs(weekly_pnl) / balance * 100
        if loss_pct >= weekly_limit_pct:
            msg = (f"Weekly loss limit hit ({loss_pct:.2f}% ≥ {weekly_limit_pct}%). "
                   "No new trades this week.")
            repo.log_system_event("WARNING", "WEEKLY_LOSS_LIMIT", msg)
            return LimitCheckResult(allowed=False, reason=msg)
    return LimitCheckResult(allowed=True)


def _check_spread(symbol: str) -> LimitCheckResult:
    max_spreads = get("risk.max_spread_pips", {})
    max_spread = max_spreads.get(symbol)
    if max_spread is None:
        return LimitCheckResult(allowed=True)

    try:
        current_spread = get_current_spread_pips(symbol)
    except Exception as e:
        log.warning("Could not get spread for %s: %s", symbol, e)
        return LimitCheckResult(allowed=True)  # Fail open — don't block on spread check error

    if current_spread > max_spread:
        return LimitCheckResult(
            allowed=False,
            reason=(f"{symbol} spread too wide ({current_spread:.1f} pips > "
                    f"max {max_spread:.1f} pips). Skipping entry."),
        )
    return LimitCheckResult(allowed=True)


def _get_weekly_pnl() -> float:
    """Sum daily P&L for the current ISO week (Mon–Sun)."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())  # Monday

    weekly_total = 0.0
    for i in range(7):
        day = week_start + timedelta(days=i)
        if day > today:
            break
        date_str = day.isoformat()
        try:
            with repo.session_scope() as s:
                stat = s.query(repo.DailyStat).filter_by(date=date_str).first()
                if stat and stat.pnl_usd:
                    weekly_total += stat.pnl_usd
        except Exception:
            pass

    return weekly_total


def trigger_emergency_stop_if_needed(balance: float, equity: float) -> None:
    """Auto-trigger emergency stop if equity drops below a critical threshold."""
    # Hard floor: if equity < 50% of balance, emergency stop
    if equity < balance * 0.5:
        log.critical("🚨 Equity %.2f < 50%% of balance %.2f — triggering emergency stop", equity, balance)
        repo.trigger_emergency_stop()
