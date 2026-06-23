from fastapi import FastAPI, Body
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc
import os
import time

from src.core.logger import setup_root_logger, get_logger
setup_root_logger()
log = get_logger(__name__)

from src.db.repository import session_scope, get_today_pnl, get_today_trade_count, count_open_trades, is_emergency_stop, get_setting, set_setting
from src.db.models import Trade, TradeHistory, DailyStat

app = FastAPI(title="FX Bot Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/status")
def get_status():
    return {
        "status": "Active",
        "emergency_stop": is_emergency_stop()
    }

@app.post("/api/trading/toggle")
def toggle_trading(payload: dict = Body(...)):
    from src.db.repository import trigger_emergency_stop, reset_emergency_stop
    enabled = payload.get("enabled", False)
    if enabled:
        reset_emergency_stop()
    else:
        trigger_emergency_stop()
    return {"status": "Active" if enabled else "EMERGENCY_STOP", "emergency_stop": not enabled}

def trigger_dynamic_sync():
    """Ensure MT5 is connected and run reconciliation/sync."""
    from src.data.mt5_connection import connect, is_connected
    from src.execution.reconciler import reconcile
    try:
        if not is_connected():
            connect(max_retries=1)
        if is_connected():
            reconcile()
    except Exception as e:
        log.error("Dynamic sync failed: %s", e)


@app.get("/api/account")
def get_account_api():
    from src.data.mt5_connection import connect, is_connected
    import MetaTrader5 as mt5
    
    try:
        if not is_connected():
            connect(max_retries=1)
        if not is_connected():
            return {"error": "MT5 not connected"}
            
        acc = mt5.account_info()
        if acc:
            return {
                "login": acc.login,
                "balance": acc.balance,
                "equity": acc.equity,
                "currency": acc.currency,
                "margin_free": acc.margin_free
            }
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Could not get account info"}


@app.get("/api/stats/today")
def get_stats_today():
    trigger_dynamic_sync()
    from datetime import date
    today_str = date.today().isoformat()
    with session_scope() as s:
        stat = s.query(DailyStat).filter_by(date=today_str).first()
        if stat:
            trades = stat.trades_opened or 0
            wins = stat.wins or 0
            losses = stat.losses or 0
            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            pnl = stat.pnl_usd or 0.0
        else:
            trades = 0
            win_rate = 0.0
            pnl = 0.0

    return {
        "pnl_usd": round(pnl, 2),
        "trades": trades,
        "win_rate": round(win_rate, 1),
        "open_trades": count_open_trades()
    }


@app.get("/api/trades/open")
def get_open_trades_api():
    trigger_dynamic_sync()
    with session_scope() as s:
        trades = s.query(Trade).order_by(desc(Trade.opened_at)).all()
        return [
            {
                "ticket": t.mt5_ticket,
                "symbol": t.symbol,
                "direction": t.direction,
                "lot_size": t.lot_size,
                "open_price": t.open_price,
                "sl_price": t.sl_price,
                "tp_price": t.tp_price,
                "score": t.signal_score,
                "opened_at": (t.opened_at.isoformat() + "Z") if t.opened_at else None
            }
            for t in trades
        ]

@app.get("/api/trades/history")
def get_trade_history_api():
    with session_scope() as s:
        history = s.query(TradeHistory).order_by(desc(TradeHistory.closed_at)).limit(20).all()
        return [
            {
                "ticket": t.mt5_ticket,
                "symbol": t.symbol,
                "direction": t.direction,
                "lot_size": t.lot_size,
                "pnl_usd": t.pnl_usd,
                "pips": t.pips,
                "close_reason": t.close_reason,
                "closed_at": (t.closed_at.isoformat() + "Z") if t.closed_at else None,
                "ai_analysis": t.ai_analysis,
            }
            for t in history
        ]

@app.get("/api/ai/recent-signals")
def get_ai_recent_signals():
    """Return the last 10 signals with AI data for the dashboard."""
    from src.db.models import Signal
    with session_scope() as s:
        signals = s.query(Signal).filter(
            Signal.ai_sentiment.isnot(None)
        ).order_by(desc(Signal.created_at)).limit(10).all()
        return [
            {
                "symbol": sig.symbol,
                "direction": sig.direction,
                "score": sig.score,
                "ai_sentiment": sig.ai_sentiment,
                "ai_score_adjustment": sig.ai_score_adjustment,
                "ai_summary": sig.ai_summary,
                "passed": sig.passed_threshold,
                "created_at": (sig.created_at.isoformat() + "Z") if sig.created_at else None,
            }
            for sig in signals
        ]

@app.get("/api/signals")
def get_recent_signals_api():
    """Return the last 10 strategy scans (including skipped/neutral ones) for the dashboard scanner log."""
    from src.db.models import Signal
    with session_scope() as s:
        signals = s.query(Signal).order_by(desc(Signal.created_at)).limit(10).all()
        return [
            {
                "symbol": sig.symbol,
                "direction": sig.direction,
                "score": sig.score,
                "score_trend": sig.score_trend,
                "score_structure": sig.score_structure,
                "score_liquidity": sig.score_liquidity,
                "score_momentum": sig.score_momentum,
                "score_session": sig.score_session,
                "passed": sig.passed_threshold,
                "reason_skip": sig.reason_skip,
                "created_at": (sig.created_at.isoformat() + "Z") if sig.created_at else None,
            }
            for sig in signals
        ]

@app.post("/api/signals/clear")
def clear_signals_api():
    """Clear all scanner activity logs from the database."""
    from src.db.repository import clear_signals
    clear_signals()
    return {"success": True}


@app.get("/api/settings/symbols")
def get_symbols_api():
    symbols_str = get_setting("symbols", "XAUUSD,EURUSD,GBPUSD")
    return {"symbols": [s.strip() for s in symbols_str.split(",") if s.strip()]}

@app.post("/api/settings/symbols")
def update_symbols_api(payload: dict = Body(...)):
    symbols = payload.get("symbols", [])
    if not isinstance(symbols, list):
        return {"error": "Expected a list of symbols"}
    symbols_str = ",".join(s.strip().upper() for s in symbols if s.strip())
    set_setting("symbols", symbols_str)
    return {"success": True, "symbols": symbols_str.split(",")}

# ── AI Settings ──────────────────────────────────────────────────────────────

@app.get("/api/settings/ai")
def get_ai_settings():
    provider = get_setting("ai_provider", "gemini")
    model = get_setting("ai_model", "gemini-2.0-flash")
    raw_key = get_setting("ai_api_key", "")
    masked_key = (raw_key[:6] + "..." + raw_key[-4:]) if len(raw_key) > 10 else ("" if not raw_key else "***")
    budget = float(get_setting("ai_monthly_budget", "5.00"))
    spend = float(get_setting("ai_spend_mtd", "0.0"))
    return {
        "provider": provider, "model": model,
        "api_key_set": bool(raw_key), "api_key_masked": masked_key,
        "monthly_budget": budget, "spend_mtd": round(spend, 4),
        "budget_remaining": round(max(0, budget - spend), 4),
        "ai_enabled": bool(raw_key) and spend < budget,
    }

@app.post("/api/settings/ai")
def update_ai_settings(payload: dict = Body(...)):
    if "provider" in payload:
        set_setting("ai_provider", payload["provider"])
    if "model" in payload:
        set_setting("ai_model", payload["model"])
    if "api_key" in payload and payload["api_key"]:
        set_setting("ai_api_key", payload["api_key"])
    if "monthly_budget" in payload:
        set_setting("ai_monthly_budget", str(float(payload["monthly_budget"])))
    return {"success": True}

@app.post("/api/settings/ai/reset-spend")
def reset_ai_spend():
    set_setting("ai_spend_mtd", "0.0")
    return {"success": True, "message": "Monthly AI spend reset to $0.00"}

@app.post("/api/settings/ai/test")
async def test_ai_settings_api(payload: dict = Body(...)):
    provider = payload.get("provider", "gemini")
    model = payload.get("model", "")
    api_key = payload.get("api_key", "")
    
    from src.ai.client import test_ai_connection
    res = await test_ai_connection(provider, model, api_key)
    return res

# ── Manual Scan ──────────────────────────────────────────────────────────────

@app.post("/api/scanner/scan")
async def trigger_manual_scan():
    import MetaTrader5 as mt5
    from src.core.config import load_config, get as cfg_get
    from src.data.account_info import get_account, get_server_time
    from src.data.cache import get_cached_candles
    from src.data.candles import get_candles
    from src.data.symbol_info import get_symbol_spec
    from src.strategy.session_filter import detect_session
    from src.strategy.trend import detect_trend
    from src.strategy.structure import detect_bos
    from src.strategy.liquidity import detect_liquidity_sweep
    from src.strategy.momentum import detect_momentum
    from src.scoring.engine import score_signal
    from src.ai.client import is_ai_enabled, analyze_pre_trade_sentiment
    from src.risk.limits import check_all_limits
    from src.risk.position_sizing import calc_lot_size, calc_sl_pips_from_atr
    from src.execution.order_manager import open_trade
    from src.telegram.notifications import notify_trade_opened
    import src.db.repository as repo
    import src.data.mt5_connection as mt5_conn
    if not mt5_conn.connect():
        return {"success": False, "error": "MT5 not initialized"}
        
    try:
        account = get_account()
    except Exception as e:
        return {"success": False, "error": f"Cannot fetch account: {e}"}
        
    db_symbols = repo.get_setting("symbols", "XAUUSD,EURUSD,GBPUSD")
    symbols = [s.strip() for s in db_symbols.split(",") if s.strip()]
    
    scanned = []
    trades_placed = []
    
    for symbol in symbols:
        try:
            spec = get_symbol_spec(symbol)
            df_h1 = get_cached_candles(symbol, "H1", fetcher=get_candles, count=300)
            df_m15 = get_cached_candles(symbol, "M15", fetcher=get_candles, count=200)
            
            server_ts = get_server_time()
            session = detect_session(server_ts)
            trend = detect_trend(df_h1)
            bos = detect_bos(df_m15)
            sweep = detect_liquidity_sweep(df_m15)
            momentum = detect_momentum(df_m15)
            
            breakdown = score_signal(symbol, trend, bos, sweep, momentum, session)
            
            ai_sentiment = None
            ai_score_adjustment = 0.0
            ai_summary = None
            
            if is_ai_enabled() and breakdown.direction != "NEUTRAL":
                try:
                    ai_result = await analyze_pre_trade_sentiment(symbol, breakdown.direction)
                    ai_sentiment = ai_result.get("sentiment", "NEUTRAL")
                    ai_score_adjustment = float(ai_result.get("score_adjustment", 0.0))
                    ai_summary = ai_result.get("summary", "")
                except Exception as e:
                    ai_summary = f"AI error: {e}"
            
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
            
            final_score = breakdown.total  # AI no longer modifies score — kept deterministic for backtesting
            min_score = cfg_get("scoring.min_score", 65)
            
            scanned.append({
                "symbol": symbol,
                "direction": breakdown.direction,
                "score": final_score,
                "ai_sentiment": ai_sentiment,
                "ai_summary": ai_summary,
                "passed": breakdown.passed
            })
            
            # Place order if qualified and we have space
            if breakdown.passed and breakdown.direction != "NEUTRAL":
                if repo.count_open_trades() < cfg_get("risk.max_open_trades", 1):
                    limit_check = check_all_limits(symbol, account.balance)
                    if limit_check.allowed:
                        sl_price_dist = calc_sl_pips_from_atr(df_m15)
                        if sl_price_dist > 0:
                            pip_size = spec.point * 10
                            sl_pips = sl_price_dist / pip_size
                            lot = calc_lot_size(account.balance, sl_pips, spec)
                            current_price = float(df_m15["close"].iloc[-1])
                            
                            if breakdown.direction == "BUY":
                                sl = current_price - sl_price_dist
                                tp = current_price + sl_price_dist * cfg_get("risk.tp_risk_reward", 2.0)
                            else:
                                sl = current_price + sl_price_dist
                                tp = current_price - sl_price_dist * cfg_get("risk.tp_risk_reward", 2.0)
                                
                            result = open_trade(symbol, breakdown.direction, lot, sl, tp, comment=f"fxbot-{int(breakdown.total)}")
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
                                trades_placed.append(symbol)
                                try:
                                    await notify_trade_opened(
                                        symbol, breakdown.direction, lot, current_price, sl, tp,
                                        breakdown.total, session.label.value,
                                    )
                                except Exception:
                                    pass
        except Exception as ex:
            scanned.append({"symbol": symbol, "error": str(ex)})
            
    return {"success": True, "scanned": scanned, "trades_placed": trades_placed}

# ── MT5 News ─────────────────────────────────────────────────────────────────

# In-memory caches to prevent rate limiting (HTTP 429)
_news_cache = {
    "data": None,
    "last_fetched": 0.0,
    "ttl": 300.0  # 5 minutes
}

_calendar_cache = {
    "data": None,
    "last_fetched": 0.0,
    "ttl": 900.0  # 15 minutes
}

@app.get("/api/news")
def get_mt5_news():
    now_time = time.time()
    if _news_cache["data"] is not None and (now_time - _news_cache["last_fetched"]) < _news_cache["ttl"]:
        return _news_cache["data"]

    import httpx
    import xml.etree.ElementTree as ET
    from datetime import datetime
    try:
        url = "https://finance.yahoo.com/news/rss"
        resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5.0)
        if resp.status_code != 200:
            if _news_cache["data"] is not None:
                return _news_cache["data"]
            return []
        
        root = ET.fromstring(resp.text)
        result = []
        for item in root.findall(".//item")[:20]:
            title_node = item.find("title")
            pub_date = item.find("pubDate")
            result.append({
                "subject": title_node.text.strip() if title_node is not None and title_node.text else "No Subject",
                "category": "Market News",
                "time": int(datetime.utcnow().timestamp()), # Fallback timestamp
            })
        _news_cache["data"] = result
        _news_cache["last_fetched"] = now_time
        return result
    except Exception:
        if _news_cache["data"] is not None:
            return _news_cache["data"]
        return []

@app.get("/api/calendar")
async def get_forex_calendar():
    now_time = time.time()
    if _calendar_cache["data"] is not None and (now_time - _calendar_cache["last_fetched"]) < _calendar_cache["ttl"]:
        return _calendar_cache["data"]

    import httpx
    import re
    from datetime import datetime
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            
        html = resp.text
        
        # Try to extract the calendar table body or fallback to parsing the entire html for <tr>
        tables = re.findall(r'<table[^>]*>(.*?)</table>', html, re.DOTALL)
        if tables:
            tbody_content = tables[0]
        else:
            tbodies = re.findall(r'<tbody[^>]*>(.*?)</tbody>', html, re.DOTALL)
            if tbodies:
                tbody_content = tbodies[0]
            else:
                tbody_content = html
                
        tr_pattern = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
        trs = tr_pattern.findall(tbody_content)
        
        # Today's date formats to match
        now = datetime.utcnow()
        day_str = str(now.day)
        month_str = now.strftime('%B')
        year_str = str(now.year)
        
        # We check both "June 15, 2026" and "June 05, 2026"
        date_pattern1 = f"{month_str} {day_str}, {year_str}"
        date_pattern2 = f"{month_str} {now.strftime('%d')}, {year_str}"
        
        current_date = ""
        events = []
        
        for tr in trs:
            # Check for date header
            date_match = re.search(r'text-center font-semibold[^>]*>(.*?)</div>', tr)
            if date_match:
                current_date = date_match.group(1).strip()
                continue
                
            # We only want today's events
            is_today = (date_pattern1 in current_date) or (date_pattern2 in current_date)
            if not is_today:
                continue
                
            if 'flag_flag' in tr:
                # Extract currency/country
                cur_match = re.search(r'flag_flag--([A-Z]{2})__', tr)
                if not cur_match:
                    cur_match = re.search(r'data-test="flag-([A-Z]{2})"', tr)
                currency = cur_match.group(1) if cur_match else "USD"
                
                # Map flag code to currency
                country_to_currency = {
                    "US": "USD", "EU": "EUR", "UK": "GBP", "JP": "JPY", "NZ": "NZD",
                    "AU": "AUD", "CA": "CAD", "CH": "CHF", "SE": "SEK", "NO": "NOK",
                    "CN": "CNY", "HK": "HKD", "SG": "SGD"
                }
                currency = country_to_currency.get(currency.upper(), currency.upper())
                
                # Extract event name
                event_match = re.search(r'<a href="[^"]*economic-calendar/[^"]*"[^>]*>(.*?)</a>', tr, re.DOTALL)
                event_title = ""
                if event_match:
                    event_title = re.sub(r'<[^>]*>', '', event_match.group(1)).strip()
                    event_title = re.sub(r'\s+', ' ', event_title)
                
                if not event_title:
                    continue
                    
                # Extract impact
                opacity_60_count = tr.count('opacity-60')
                if opacity_60_count >= 3:
                    impact = "High"
                elif opacity_60_count == 2:
                    impact = "Medium"
                else:
                    impact = "Low"
                    
                # Only keep High and Medium impact events
                if impact.lower() not in ["high", "medium"]:
                    continue
                    
                # Extract time
                time_tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL)
                time_str = "All Day"
                if len(time_tds) > 1:
                    t_val = re.sub(r'<[^>]*>', '', time_tds[1]).strip()
                    if t_val:
                        time_str = t_val
                        
                events.append({
                    "time": time_str,
                    "currency": currency,
                    "event": event_title,
                    "impact": impact,
                    "forecast": "",
                    "previous": "",
                })
                
        result = events[:15]
        _calendar_cache["data"] = result
        _calendar_cache["last_fetched"] = now_time
        return result
    except Exception as ex:
        if _calendar_cache["data"] is not None:
            return _calendar_cache["data"]
        return [{"event": f"Calendar unavailable: {ex}", "impact": "low", "currency": "", "time": ""}]


@app.post("/api/trades/close")
def close_trade_api(payload: dict = Body(...)):
    from src.execution.order_manager import close_trade as mt5_close_trade
    from src.db.repository import get_trade_by_ticket
    from src.execution.position_monitor import monitor_positions
    from src.strategy.session_filter import detect_session
    from src.data.account_info import get_server_time
    
    ticket = payload.get("ticket")
    if not ticket:
        return {"error": "Ticket is required"}
        
    trade = get_trade_by_ticket(ticket)
    if not trade:
        return {"error": f"Trade ticket {ticket} not found in database"}
        
    result = mt5_close_trade(
        ticket=trade.mt5_ticket,
        symbol=trade.symbol,
        direction=trade.direction,
        lot_size=trade.lot_size
    )
    if result.success:
        try:
            # Trigger immediate position monitor to sync the DB status
            server_ts = get_server_time()
            session = detect_session(server_ts)
            monitor_positions(session)
        except Exception as e:
            print(f"Error updating positions after manual close: {e}")
        return {"success": True}
    else:
        return {"error": result.error or "Failed to close trade in MT5"}

# Mount static files at the root
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

