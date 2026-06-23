"""
src/telegram/notifications.py
──────────────────────────────
All notification templates for trade events, summaries, errors, heartbeat.
All calls are async fire-and-forget — never block the main bot loop.
"""
from __future__ import annotations

from datetime import datetime

from src.core.logger import get_logger
from src.telegram.client import send_message

log = get_logger(__name__)

_EMOJI = {
    "BUY": "🟢",
    "SELL": "🔴",
    "WIN": "✅",
    "LOSS": "❌",
    "ALERT": "⚠️",
    "INFO": "ℹ️",
    "HEART": "💓",
}


async def notify_trade_opened(
    symbol: str,
    direction: str,
    lot_size: float,
    open_price: float,
    sl_price: float,
    tp_price: float,
    score: float,
    session: str,
) -> None:
    emoji = _EMOJI.get(direction, "")
    text = (
        f"{emoji} <b>Trade Opened</b>\n\n"
        f"<b>Pair:</b> {symbol}\n"
        f"<b>Direction:</b> {direction}\n"
        f"<b>Lots:</b> {lot_size:.2f}\n"
        f"<b>Entry:</b> {open_price:.5f}\n"
        f"<b>SL:</b> {sl_price:.5f}\n"
        f"<b>TP:</b> {tp_price:.5f}\n"
        f"<b>Score:</b> {score:.1f}/100\n"
        f"<b>Session:</b> {session}\n"
        f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"
    )
    await send_message(text)


async def notify_trade_closed(trade, pnl: float, pips: float, reason: str) -> None:
    emoji = _EMOJI["WIN"] if pnl >= 0 else _EMOJI["LOSS"]
    sign = "+" if pnl >= 0 else ""
    text = (
        f"{emoji} <b>Trade Closed</b>\n\n"
        f"<b>Pair:</b> {trade.symbol}\n"
        f"<b>Direction:</b> {trade.direction}\n"
        f"<b>Reason:</b> {reason}\n"
        f"<b>Pips:</b> {sign}{pips:.1f}\n"
        f"<b>P&amp;L:</b> {sign}${pnl:.2f}\n"
        f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"
    )
    await send_message(text)


async def notify_daily_summary(
    date_str: str,
    trades: int,
    wins: int,
    losses: int,
    pnl: float,
    balance: float,
) -> None:
    win_rate = (wins / trades * 100) if trades > 0 else 0
    sign = "+" if pnl >= 0 else ""
    text = (
        f"📊 <b>Daily Summary — {date_str}</b>\n\n"
        f"<b>Trades:</b> {trades}\n"
        f"<b>Win Rate:</b> {win_rate:.1f}%  ({wins}W / {losses}L)\n"
        f"<b>P&amp;L:</b> {sign}${pnl:.2f}\n"
        f"<b>Balance:</b> ${balance:,.2f}\n"
    )
    await send_message(text)


async def notify_weekly_summary(
    week_label: str,
    trades: int,
    win_rate: float,
    profit_factor: float,
    pnl: float,
    max_dd: float,
) -> None:
    text = (
        f"📈 <b>Weekly Summary — {week_label}</b>\n\n"
        f"<b>Trades:</b> {trades}\n"
        f"<b>Win Rate:</b> {win_rate:.1f}%\n"
        f"<b>Profit Factor:</b> {profit_factor:.2f}\n"
        f"<b>Net P&amp;L:</b> ${pnl:+.2f}\n"
        f"<b>Max Drawdown:</b> {max_dd:.2f}%\n"
    )
    await send_message(text)


async def notify_error(message: str) -> None:
    text = f"{_EMOJI['ALERT']} <b>FX Bot Error</b>\n\n{message}"
    await send_message(text)


async def notify_heartbeat(balance: float, equity: float, open_trades: int) -> None:
    text = (
        f"{_EMOJI['HEART']} <b>Bot Heartbeat</b>\n\n"
        f"<b>Status:</b> Running ✅\n"
        f"<b>Balance:</b> ${balance:,.2f}\n"
        f"<b>Equity:</b> ${equity:,.2f}\n"
        f"<b>Open Trades:</b> {open_trades}\n"
        f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"
    )
    await send_message(text)


async def notify_emergency_stop(reason: str) -> None:
    text = (
        f"🚨 <b>EMERGENCY STOP TRIGGERED</b>\n\n"
        f"<b>Reason:</b> {reason}\n"
        f"All new orders are now blocked until manually reset.\n"
        f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</i>"
    )
    await send_message(text)
