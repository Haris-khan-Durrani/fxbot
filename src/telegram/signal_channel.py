"""
src/telegram/signal_channel.py
───────────────────────────────
Public signal channel broadcaster.

Sends clean, follower-facing trade signals to a separate Telegram
group/channel. Uses the same bot token as private notifications but
targets a different chat ID configured in telegram_signals.channel_id.

Rules enforced here:
  - No lot sizes in any public message (account-size-dependent)
  - No account balance in any public message
  - No internal details (DB IDs, ATR values, raw MT5 codes)
  - Always includes disclaimer on opened signals
  - Failure to send NEVER raises or blocks any other code path
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.core.config import get
from src.core.logger import get_logger

log = get_logger(__name__)

# ── Pip size map — used to compute pip distances from prices ─────────────────
# 1 pip = point * 10 for all symbols in our universe.
# XAUUSD: point=0.01 → pip=0.10; Forex 5-digit: point=0.00001 → pip=0.0001
_PIP_SIZES: dict[str, float] = {
    "XAUUSD": 0.10,
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "AUDUSD": 0.0001,
    "NZDUSD": 0.0001,
}
_DEFAULT_PIP_SIZE = 0.0001


def _pip_size(symbol: str) -> float:
    return _PIP_SIZES.get(symbol.upper(), _DEFAULT_PIP_SIZE)


def _price_fmt(symbol: str, price: float) -> str:
    """Format price with appropriate decimal places for the symbol."""
    if "XAUUSD" in symbol.upper():
        return f"{price:,.2f}"
    return f"{price:.5f}"


def _duration_str(opened_at: Optional[datetime], closed_at: Optional[datetime]) -> str:
    """Format trade duration as 'Xh Ym'."""
    if opened_at is None or closed_at is None:
        return "—"
    try:
        delta = closed_at - opened_at
        total_minutes = int(delta.total_seconds() / 60)
        hours, mins = divmod(total_minutes, 60)
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "—"


def _reason_label(reason: str) -> str:
    """Map internal close reasons to clean public labels."""
    mapping = {
        "TP": "TP ✅",
        "SL": "SL ❌",
        "TSL": "Trailing SL 📉",
        "BE": "Break-Even 🛡️",
        "MANUAL": "Manual Close 🤚",
    }
    return mapping.get(reason.upper(), reason)


# ── Formatters ───────────────────────────────────────────────────────────────

def format_signal_open(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    score: Optional[float] = None,
    session: Optional[str] = None,
    ai_commentary: Optional[str] = None,
) -> str:
    """
    Build the public-facing 'Trade Opened' message.

    No lot sizes. No account balance. Always includes disclaimer.
    Pip distances and RR are computed from prices.
    """
    pip = _pip_size(symbol)
    dir_emoji = "🟢" if direction == "BUY" else "🔴"
    dir_label = direction.upper()

    sl_pips = abs(entry_price - sl_price) / pip
    tp_pips = abs(tp_price - entry_price) / pip
    rr = (tp_pips / sl_pips) if sl_pips > 0 else 0.0

    sl_sign = "−" if direction == "BUY" else "+"
    tp_sign = "+" if direction == "BUY" else "−"

    entry_fmt = _price_fmt(symbol, entry_price)
    sl_fmt    = _price_fmt(symbol, sl_price)
    tp_fmt    = _price_fmt(symbol, tp_price)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"{dir_emoji} <b>SIGNAL — {dir_label} {symbol}</b>",
        "",
        f"📍 <b>Entry:</b>   {entry_fmt}",
        f"🛑 <b>Stop:</b>    {sl_fmt}  ({sl_sign}{sl_pips:.1f} pips)",
        f"🎯 <b>Target:</b>  {tp_fmt}  ({tp_sign}{tp_pips:.1f} pips)",
        f"⚖️ <b>RR:</b>      1 : {rr:.1f}",
    ]

    if get("telegram_signals.include_score", True) and score is not None:
        lines.append(f"📊 <b>Score:</b>   {score:.1f} / 100")

    if get("telegram_signals.include_session", True) and session:
        lines.append(f"🕐 <b>Session:</b> {session.upper()}")

    if get("telegram_signals.include_commentary", False) and ai_commentary:
        lines.append(f"💬 <i>{ai_commentary}</i>")

    lines += [
        f"⏰ <b>Time:</b>    {now_utc}",
        "",
        "⚠️ <i>For reference only. Not financial advice.</i>",
    ]

    return "\n".join(lines)


def format_signal_close(
    symbol: str,
    direction: str,
    pips: float,
    pnl_usd: float,
    close_reason: str,
    score: Optional[float] = None,
    opened_at: Optional[datetime] = None,
    closed_at: Optional[datetime] = None,
) -> str:
    """
    Build the public-facing 'Trade Closed' message.

    No lot sizes. No account balance.
    """
    pips_sign = "+" if pips >= 0 else ""
    pnl_sign  = "+" if pnl_usd >= 0 else ""
    dir_emoji = "🟢" if direction == "BUY" else "🔴"

    close_utc = (
        closed_at.strftime("%Y-%m-%d %H:%M UTC")
        if closed_at
        else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    )

    lines = [
        f"🔴 <b>CLOSED — {direction.upper()} {symbol}</b>",
        "",
        f"📊 <b>Result:</b>  {pips_sign}{pips:.1f} pips  |  {pnl_sign}${pnl_usd:.2f}",
        f"🏁 <b>Reason:</b>  {_reason_label(close_reason)}",
        f"⏱️ <b>Duration:</b> {_duration_str(opened_at, closed_at)}",
    ]

    if score is not None:
        lines.append(f"📈 <b>Score was:</b> {score:.1f} / 100")

    lines.append(f"⏰ <b>Closed:</b>  {close_utc}")

    return "\n".join(lines)


# ── Sender ───────────────────────────────────────────────────────────────────

async def send_signal_notification(message: str) -> None:
    """
    Send a message to the signal channel/group.

    Uses the same bot token as private notifications.
    Reads telegram_signals.channel_id from config.
    All failures are caught silently — never raises, never blocks
    the private notification path or trading logic.
    """
    if not get("telegram_signals.enabled", False):
        return

    channel_id = get("telegram_signals.channel_id", "")
    if not channel_id:
        log.warning("Signal channel: telegram_signals.enabled=true but channel_id is empty — skipping.")
        return

    try:
        from src.telegram.client import _init_telegram, _bot, _enabled
        _init_telegram()
        if not _enabled or _bot is None:
            log.warning("Signal channel: Telegram bot not initialized — skipping signal send.")
            return

        await _bot.send_message(
            chat_id=channel_id,
            text=message,
            parse_mode="HTML",
        )
        log.info("Signal channel: message sent to %s", channel_id)

    except Exception as e:
        # Intentional silent swallow — signal channel failure must NEVER
        # block trading, private notifications, or any other code path.
        log.warning("Signal channel: send failed (non-fatal): %s", e)
