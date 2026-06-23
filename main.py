"""
main.py
────────
FX Bot main entry point.
Runs the bot main loop: connect MT5, reconcile, scan symbols, score signals,
manage positions, send Telegram notifications.
"""
from __future__ import annotations

import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.core.config import get, load_config
from src.core.logger import get_logger, setup_root_logger

setup_root_logger()
log = get_logger("main")

import src.data.mt5_connection as mt5_conn
from src.data.account_info import get_account, get_open_positions, get_server_time
from src.data.cache import get_cached_candles
from src.data.candles import get_candles
from src.data.symbol_info import get_symbol_spec
from src.db.init_db import init_database
from src.db import repository as repo
from src.execution.order_manager import open_trade
from src.execution.reconciler import reconcile
from src.execution.position_monitor import monitor_positions
from src.risk.limits import check_all_limits, trigger_emergency_stop_if_needed
from src.risk.position_sizing import calc_lot_size, calc_sl_pips_from_atr
from src.scoring.engine import score_signal
from src.strategy.liquidity import detect_liquidity_sweep
from src.strategy.momentum import detect_momentum
from src.strategy.session_filter import detect_session
from src.strategy.structure import detect_bos
from src.strategy.trend import detect_trend
from src.telegram.notifications import (
    notify_error, notify_heartbeat, notify_trade_opened,
)

_RUNNING = True
_LAST_HEARTBEAT_DAY: int = -1


def _handle_shutdown(sig, frame):
    global _RUNNING
    log.warning("Shutdown signal received (%s). Stopping bot ...", sig)
    _RUNNING = False


signal.signal(signal.SIGINT, _handle_shutdown)
signal.signal(signal.SIGTERM, _handle_shutdown)


async def _scan_symbol(symbol: str, account) -> None:
    """Analyse a single symbol and open a trade if signal passes all gates."""
    try:
        spec = get_symbol_spec(symbol)
    except Exception as e:
        log.warning("Could not get spec for %s: %s", symbol, e)
        return

    # ── Fetch candles ─────────────────────────────────────────────
    try:
        df_h1 = get_cached_candles(symbol, "H1", fetcher=get_candles, count=300)
        df_m15 = get_cached_candles(symbol, "M15", fetcher=get_candles, count=200)
    except Exception as e:
        log.error("Candle fetch failed for %s: %s", symbol, e)
        return

    # ── Strategy signals ──────────────────────────────────────────
    server_ts = get_server_time()
    session = detect_session(server_ts)
    trend = detect_trend(df_h1)
    bos = detect_bos(df_m15)
    sweep = detect_liquidity_sweep(df_m15)
    momentum = detect_momentum(df_m15)

    # ── Signal scoring ────────────────────────────────────────────
    breakdown = score_signal(symbol, trend, bos, sweep, momentum, session)

    # ── AI Option A: Pre-Trade Sentiment Analysis ─────────────────
    ai_sentiment = None
    ai_score_adjustment = 0.0
    ai_summary = None
    try:
        from src.ai.client import is_ai_enabled, analyze_pre_trade_sentiment
        if is_ai_enabled() and breakdown.direction != "NEUTRAL":
            ai_result = await analyze_pre_trade_sentiment(symbol, breakdown.direction)
            ai_sentiment = ai_result.get("sentiment", "NEUTRAL")
            ai_score_adjustment = float(ai_result.get("score_adjustment", 0.0))
            ai_summary = ai_result.get("summary", "")
            # Apply AI adjustment to the total score
            adjusted_total = breakdown.total + ai_score_adjustment
            log.info(
                "AI Sentiment [%s %s]: %s | adj=%+.1f | new_score=%.1f",
                symbol, breakdown.direction, ai_sentiment, ai_score_adjustment, adjusted_total
            )
    except Exception as e:
        log.warning("AI pre-trade analysis skipped: %s", e)

    # Save every signal to DB (even rejected ones — useful for analytics)
    repo.insert_signal(
        symbol=symbol,
        direction=breakdown.direction,
        score=breakdown.total,
        score_trend=breakdown.trend,
        score_structure=breakdown.structure,
        score_liquidity=breakdown.liquidity,
        score_momentum=breakdown.momentum,
        score_session=breakdown.session,
        passed=breakdown.passed,
        signal_price=float(df_m15["close"].iloc[-1]),
        reason_skip=breakdown.skip_reason,
        ai_sentiment=ai_sentiment,
        ai_score_adjustment=ai_score_adjustment if ai_score_adjustment else None,
        ai_summary=ai_summary,
    )

    if not breakdown.passed or breakdown.direction == "NEUTRAL":
        return

    # ── Risk gates ────────────────────────────────────────────────
    limit_check = check_all_limits(symbol, account.balance)
    if not limit_check.allowed:
        log.info("Signal blocked by risk limits: %s", limit_check.reason)
        return

    # ── Position sizing ───────────────────────────────────────────
    sl_price_dist = calc_sl_pips_from_atr(df_m15)
    if sl_price_dist <= 0:
        log.warning("ATR-based SL is zero for %s, skipping.", symbol)
        return

    pip_size = spec.point * 10
    sl_pips = sl_price_dist / pip_size

    lot = calc_lot_size(account.balance, sl_pips, spec)

    current_price = float(df_m15["close"].iloc[-1])
    if breakdown.direction == "BUY":
        sl = current_price - sl_price_dist
        tp = current_price + sl_price_dist * get("risk.tp_risk_reward", 2.0)
    else:
        sl = current_price + sl_price_dist
        tp = current_price - sl_price_dist * get("risk.tp_risk_reward", 2.0)

    # ── Execute ───────────────────────────────────────────────────
    log.info("Placing order: %s %s %.2f lots  SL=%.5f  TP=%.5f  Score=%.1f",
             breakdown.direction, symbol, lot, sl, tp, breakdown.total)

    result = open_trade(symbol, breakdown.direction, lot, sl, tp,
                        comment=f"fxbot-{int(breakdown.total)}")

    if result.success and result.ticket:
        repo.insert_trade(
            mt5_ticket=result.ticket,
            symbol=symbol,
            direction=breakdown.direction,
            lot_size=lot,
            open_price=current_price,
            sl_price=sl,
            tp_price=tp,
            signal_score=breakdown.total,
        )
        repo.increment_daily_trades()
        await notify_trade_opened(
            symbol, breakdown.direction, lot, current_price, sl, tp,
            breakdown.total, session.label.value,
        )
        # ── Signal channel broadcast (public, fire-and-forget) ────────────
        # Always AFTER private notification and AFTER DB write.
        # Failure here is silently swallowed inside send_signal_notification.
        if get("telegram_signals.enabled", False):
            from src.telegram.signal_channel import format_signal_open, send_signal_notification
            _sig_msg = format_signal_open(
                symbol=symbol,
                direction=breakdown.direction,
                entry_price=current_price,
                sl_price=sl,
                tp_price=tp,
                score=breakdown.total,
                session=session.label.value,
                ai_commentary=ai_summary if get("telegram_signals.include_commentary", False) else None,
            )
            asyncio.create_task(send_signal_notification(_sig_msg))
    else:
        log.error("Order failed for %s: %s", symbol, result.error)
        repo.log_system_event("ERROR", "ORDER_FAILED",
                              f"{symbol} {breakdown.direction}: {result.error}")


async def _send_heartbeat_if_needed(account) -> None:
    global _LAST_HEARTBEAT_DAY
    heartbeat_hour = get("telegram.heartbeat_hour", 8)
    now_utc = datetime.now(timezone.utc)
    if now_utc.hour == heartbeat_hour and now_utc.day != _LAST_HEARTBEAT_DAY:
        open_count = repo.count_open_trades()
        await notify_heartbeat(account.balance, account.equity, open_count)
        _LAST_HEARTBEAT_DAY = now_utc.day


async def main_loop():
    interval = get("bot.loop_interval_seconds", 15)

    log.info("🚀 FX Bot starting | Interval: %ds", interval)

    # ── Startup ───────────────────────────────────────────────────
    try:
        load_config()
    except Exception as e:
        log.critical("Config error: %s", e)
        sys.exit(1)

    init_database()

    if not mt5_conn.connect():
        log.critical("Cannot connect to MT5. Exiting.")
        sys.exit(1)

    reconcile()

    log.info("✅ Bot initialized. Starting main loop ...")

    while _RUNNING:
        loop_start = time.monotonic()

        try:
            account = get_account()
        except Exception as e:
            log.error("Cannot fetch account info: %s", e)
            if not mt5_conn.ensure_connected():
                log.critical("MT5 reconnect failed. Waiting 60s ...")
                await asyncio.sleep(60)
            continue

        # Emergency stop safety check
        trigger_emergency_stop_if_needed(account.balance, account.equity)
        if repo.is_emergency_stop():
            log.warning("🚨 Emergency stop active — skipping scan.")
            await asyncio.sleep(interval)
            continue

        # Monitor open positions (trailing, break-even, closures)
        server_ts = get_server_time()
        session = detect_session(server_ts)
        monitor_positions(session)

        # Scan each symbol for new signals
        db_symbols = repo.get_setting("symbols", "XAUUSD,EURUSD,GBPUSD")
        symbols = [s.strip() for s in db_symbols.split(",") if s.strip()]
        for symbol in symbols:
            if not _RUNNING:
                break
            await _scan_symbol(symbol, account)

        # Heartbeat notification
        await _send_heartbeat_if_needed(account)

        # Loop timing
        elapsed = time.monotonic() - loop_start
        sleep_time = max(0.1, interval - elapsed)
        await asyncio.sleep(sleep_time)

    log.info("Bot stopped cleanly.")
    mt5_conn.disconnect()


if __name__ == "__main__":
    asyncio.run(main_loop())
