"""
src/execution/reconciler.py
───────────────────────────
On startup/dynamic polls: reconcile MT5 open positions against the local DB.
Inserts any MT5 positions missing from DB; marks DB records as closed
if MT5 no longer has a matching position (fetching actual close details from history).
"""
from __future__ import annotations

from src.core.logger import get_logger
from src.data.account_info import OpenPosition, get_open_positions
from src.db import repository as repo

import time

log = get_logger(__name__)

_last_reconcile = 0.0
_last_sync = 0.0


def reconcile() -> None:
    """
    Compare MT5 live positions with DB trades table and resolve discrepancies.
    Handles bot crash/reboot recovery gracefully.
    """
    global _last_reconcile
    now = time.time()
    if now - _last_reconcile < 15.0:
        return
    _last_reconcile = now

    log.info("🔄 Running open positions reconciliation ...")

    try:
        mt5_positions: list[OpenPosition] = get_open_positions()
    except Exception as e:
        log.error("Reconciliation skipped — could not fetch MT5 positions: %s", e)
        return

    mt5_tickets = {p.ticket for p in mt5_positions}
    db_trades = repo.get_open_trades()
    db_tickets = {t.mt5_ticket for t in db_trades}

    # ── MT5 positions not in DB → insert them ────────────────────────
    missing_in_db = mt5_tickets - db_tickets
    for pos in mt5_positions:
        if pos.ticket in missing_in_db:
            log.warning(
                "Reconciliation: ticket %d (%s %s) found in MT5 but NOT in DB — inserting.",
                pos.ticket, pos.symbol, pos.direction,
            )
            repo.insert_trade(
                mt5_ticket=pos.ticket,
                symbol=pos.symbol,
                direction=pos.direction,
                lot_size=pos.volume,
                open_price=pos.open_price,
                sl_price=pos.sl if pos.sl > 0 else None,
                tp_price=pos.tp if pos.tp > 0 else None,
                signal_score=None,   # Unknown — was open before crash
            )
            repo.log_system_event(
                "WARNING", "RECONCILE_INSERT",
                f"Inserted orphan MT5 position: ticket={pos.ticket} {pos.symbol} {pos.direction}",
            )

    # ── DB trades not in MT5 → mark as closed ────────────────────────
    orphan_in_db = db_tickets - mt5_tickets
    for trade in db_trades:
        if trade.mt5_ticket in orphan_in_db:
            log.warning(
                "Reconciliation: ticket %d (%s %s) in DB but NOT in MT5 — marking closed.",
                trade.mt5_ticket, trade.symbol, trade.direction,
            )
            
            # Fetch actual close price and P&L from MT5 history if possible
            close_price = None
            pnl_usd = 0.0
            pips = 0.0
            close_reason = "RECONCILE_UNKNOWN"
            
            try:
                import MetaTrader5 as mt5
                pos_deals = mt5.history_deals_get(position=trade.mt5_ticket)
                if pos_deals:
                    close_deal = next((pd for pd in pos_deals if pd.entry == mt5.DEAL_ENTRY_OUT), None)
                    if close_deal:
                        close_price = close_deal.price
                        pnl_usd = close_deal.profit + close_deal.swap + close_deal.commission
                        close_reason = "MANUAL" if close_deal.reason == 0 else "RECONCILE_CLOSE"
            except Exception as e:
                log.error("Failed to query MT5 history for orphaned ticket %d: %s", trade.mt5_ticket, e)
                
            if close_price is None:
                close_price = trade.open_price
                
            pips_multiplier = 0.0001 if "USD" in trade.symbol else 0.01
            if trade.direction == "BUY":
                pips = (close_price - trade.open_price) / pips_multiplier
            else:
                pips = (trade.open_price - close_price) / pips_multiplier
                
            closed_hist = repo.close_trade(
                mt5_ticket=trade.mt5_ticket,
                close_price=close_price,
                pips=round(pips, 1),
                pnl_usd=round(pnl_usd, 2),
                close_reason=close_reason,
                session_label="UNKNOWN",
            )
            if closed_hist:
                repo.record_trade_result(pnl_usd)
                
                repo.log_system_event(
                    "WARNING", "RECONCILE_CLOSE",
                    f"Closed ghost DB trade: ticket={trade.mt5_ticket} {trade.symbol} close_price={close_price} pnl={pnl_usd}",
                )

    if not missing_in_db and not orphan_in_db:
        log.info("✅ Reconciliation complete — DB and MT5 positions are in sync.")
    else:
        log.info("✅ Reconciliation complete — fixed %d missing, %d orphaned records.",
                 len(missing_in_db), len(orphan_in_db))
                 
    # Run sync of today's closed deals from MT5 history
    try:
        sync_closed_deals()
    except Exception as e:
        log.error("Failed to run sync_closed_deals during reconciliation: %s", e)


def sync_closed_deals() -> None:
    """
    Fetch today's closed deals from MT5 history and insert any missing ones into TradeHistory and DailyStat.
    Useful for reconciling trades closed manually or while the bot was offline.
    """
    global _last_sync
    now = time.time()
    if now - _last_sync < 15.0:
        return
    _last_sync = now

    try:
        import MetaTrader5 as mt5
    except ImportError:
        return

    if not mt5.terminal_info():
        # MT5 not initialized/connected
        return

    from datetime import datetime, timedelta
    
    # Check deals from the last 24 hours to cover today's activity safely
    start_time = datetime.now() - timedelta(days=1)
    end_time = datetime.now() + timedelta(days=1)
    
    deals = mt5.history_deals_get(start_time, end_time)
    if not deals:
        return

    # Filter for DEAL_ENTRY_OUT (closing deals)
    closing_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
    if not closing_deals:
        return

    with repo.session_scope() as s:
        from src.db.models import TradeHistory, Trade, DailyStat
        
        for d in closing_deals:
            ticket = int(d.position_id)
            if not ticket:
                continue
                
            # Skip if already in TradeHistory
            if s.query(TradeHistory).filter_by(mt5_ticket=ticket).first():
                continue
                
            # Skip if still active in Trade
            if s.query(Trade).filter_by(mt5_ticket=ticket).first():
                continue

            # This is a missing closed trade! Retrieve all deals for this position to find entry details
            pos_deals = mt5.history_deals_get(position=ticket)
            if not pos_deals:
                continue

            open_deal = next((pd for pd in pos_deals if pd.entry == mt5.DEAL_ENTRY_IN), None)
            if not open_deal:
                continue

            symbol = open_deal.symbol
            direction = "BUY" if open_deal.type == mt5.DEAL_TYPE_BUY else "SELL"
            lot_size = open_deal.volume
            open_price = open_deal.price
            close_price = d.price
            pnl_usd = d.profit + d.swap + d.commission

            # Calculate pips
            pips_multiplier = 0.0001 if "USD" in symbol else 0.01
            if direction == "BUY":
                pips = (close_price - open_price) / pips_multiplier
            else:
                pips = (open_price - close_price) / pips_multiplier

            opened_at = datetime.fromtimestamp(open_deal.time)
            closed_at = datetime.fromtimestamp(d.time)

            history = TradeHistory(
                mt5_ticket=ticket,
                symbol=symbol,
                direction=direction,
                lot_size=lot_size,
                open_price=open_price,
                close_price=close_price,
                sl_price=None,
                tp_price=None,
                pips=round(pips, 1),
                pnl_usd=round(pnl_usd, 2),
                signal_score=None,
                opened_at=opened_at,
                closed_at=closed_at,
                close_reason="MANUAL" if d.reason == 0 else "UNKNOWN",
                session="UNKNOWN",
            )
            s.add(history)

            # Record stats for the closed date
            date_str = closed_at.date().isoformat()
            stat = s.query(DailyStat).filter_by(date=date_str).first()
            if not stat:
                stat = DailyStat(date=date_str)
                s.add(stat)
            stat.trades_closed = (stat.trades_closed or 0) + 1
            stat.pnl_usd = (stat.pnl_usd or 0.0) + pnl_usd
            if pnl_usd > 0:
                stat.wins = (stat.wins or 0) + 1
            else:
                stat.losses = (stat.losses or 0) + 1

            log.info("Synced closed deal from MT5 history: ticket=%d symbol=%s profit=%.2f", ticket, symbol, pnl_usd)
