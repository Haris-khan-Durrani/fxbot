"""
src/ai/client.py
────────────────
Multi-Provider AI Co-Pilot for FX Bot.

Supports:
  - Google Gemini (gemini-2.0-flash, gemini-1.5-pro)
  - OpenAI       (gpt-4o, gpt-4o-mini, gpt-3.5-turbo)
  - Anthropic    (claude-3-5-haiku, claude-3-5-sonnet)
  - OpenRouter   (any model via unified API)

Configuration is stored in the DB settings table so users can change
provider, model, API key, and monthly budget cap from the dashboard.

Cost tracking:
  - Approximate token costs are tracked per call
  - Monthly spend (USD) is stored in settings key "ai_spend_mtd"
  - Monthly budget cap is stored in settings key "ai_monthly_budget"
  - If spend >= budget, AI features are automatically disabled until reset
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Optional

import httpx

from src.core.logger import get_logger

log = get_logger(__name__)

# ── Approximate cost per 1000 tokens (USD) ──────────────────────────────────
_COST_TABLE = {
    # Gemini
    "gemini-2.0-flash":        {"input": 0.000075, "output": 0.0003},
    "gemini-1.5-pro":          {"input": 0.00125,  "output": 0.005},
    "gemini-1.5-flash":        {"input": 0.000075, "output": 0.0003},
    # OpenAI
    "gpt-4o":                  {"input": 0.0025,   "output": 0.01},
    "gpt-4o-mini":             {"input": 0.00015,  "output": 0.0006},
    "gpt-3.5-turbo":           {"input": 0.0005,   "output": 0.0015},
    # Anthropic
    "claude-3-5-haiku-20241022": {"input": 0.0008, "output": 0.004},
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    # OpenRouter (uses their pricing, we estimate conservatively)
    "openrouter":              {"input": 0.001,    "output": 0.002},
}

_DEFAULT_SETTINGS = {
    "ai_provider":       "gemini",
    "ai_model":          "gemini-2.0-flash",
    "ai_api_key":        "",
    "ai_monthly_budget": "5.0",   # USD
    "ai_spend_mtd":      "0.0",
    "ai_spend_month":    "",      # "2024-06" to detect month rollover
}


def _get_ai_settings() -> dict:
    """Load AI settings from DB with fallbacks."""
    try:
        from src.db.repository import get_setting
        return {
            k: get_setting(k, v)
            for k, v in _DEFAULT_SETTINGS.items()
        }
    except Exception:
        return dict(_DEFAULT_SETTINGS)


def _estimate_cost(model: str, prompt_tokens: int = 500, completion_tokens: int = 200) -> float:
    """Estimate API call cost in USD."""
    costs = _COST_TABLE.get(model, _COST_TABLE["openrouter"])
    return (prompt_tokens / 1000 * costs["input"]) + (completion_tokens / 1000 * costs["output"])


def _track_spend(model: str, prompt_tokens: int = 500, completion_tokens: int = 200) -> None:
    """Add estimated cost to monthly spend tracker in DB."""
    try:
        from src.db.repository import get_setting, set_setting
        cost = _estimate_cost(model, prompt_tokens, completion_tokens)

        # Reset spend if it's a new month
        current_month = datetime.utcnow().strftime("%Y-%m")
        stored_month = get_setting("ai_spend_month", "")
        if stored_month != current_month:
            set_setting("ai_spend_month", current_month)
            set_setting("ai_spend_mtd", "0.0")

        current_spend = float(get_setting("ai_spend_mtd", "0.0"))
        new_spend = current_spend + cost
        set_setting("ai_spend_mtd", f"{new_spend:.6f}")
        log.debug("AI spend this month: $%.4f (+$%.4f)", new_spend, cost)
    except Exception as e:
        log.warning("Failed to track AI spend: %s", e)


def _is_budget_exceeded() -> bool:
    """Return True if monthly AI spend has reached the budget cap."""
    try:
        from src.db.repository import get_setting
        budget = float(get_setting("ai_monthly_budget", "5.0"))
        spend = float(get_setting("ai_spend_mtd", "0.0"))
        if spend >= budget:
            log.warning(
                "AI monthly budget cap reached ($%.2f / $%.2f). AI disabled until next month or budget is increased.",
                spend, budget
            )
            return True
        return False
    except Exception:
        return False


def is_ai_enabled() -> bool:
    """Check if AI is configured and within budget."""
    settings = _get_ai_settings()
    api_key = settings.get("ai_api_key", "").strip()
    if not api_key:
        log.warning(
            "No AI API key configured. Open the Dashboard -> Settings to add a key."
        )
        return False
    if _is_budget_exceeded():
        return False
    return True


# ── Provider Implementations ─────────────────────────────────────────────────

async def _call_gemini(prompt: str, api_key: str, model: str) -> str:
    from google import genai
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    _track_spend(model)
    return response.text.strip()


async def _call_openai(prompt: str, api_key: str, model: str, base_url: Optional[str] = None) -> str:
    from openai import AsyncOpenAI
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = AsyncOpenAI(**kwargs)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.3,
    )
    _track_spend(model)
    return resp.choices[0].message.content.strip()


async def _call_anthropic(prompt: str, api_key: str, model: str) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    msg = await client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )
    _track_spend(model)
    return msg.content[0].text.strip()


async def _call_ai(prompt: str) -> str:
    """Route to the configured AI provider."""
    settings = _get_ai_settings()
    provider = settings.get("ai_provider", "gemini").lower()
    model = settings.get("ai_model", "gemini-2.0-flash")
    api_key = settings.get("ai_api_key", "").strip()

    if provider == "gemini":
        return await _call_gemini(prompt, api_key, model)
    elif provider == "openai":
        return await _call_openai(prompt, api_key, model)
    elif provider == "openrouter":
        return await _call_openai(
            prompt, api_key, model,
            base_url="https://openrouter.ai/api/v1"
        )
    elif provider == "anthropic":
        return await _call_anthropic(prompt, api_key, model)
    else:
        raise ValueError(f"Unknown AI provider: {provider}")


def _strip_json(text: str) -> str:
    """Strip markdown fences from JSON response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _clean_ai_error(e: Exception) -> str:
    """Format raw API error exceptions into concise, user-friendly warnings."""
    err_str = str(e)
    # Check for Gemini/OpenAI 429
    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower():
        return "AI rate limit or free tier quota exceeded. Check provider/billing settings."
    # Check for invalid API key (401)
    if "401" in err_str or "API_KEY_INVALID" in err_str or "invalid api key" in err_str.lower() or "api key" in err_str.lower():
        return "Invalid API key. Please check your AI provider credentials in Settings."
    # Timeout
    if "timeout" in err_str.lower():
        return "AI analysis timed out. Check provider status or try again."
    # Default fallback - keep it short and clean
    return f"AI service error: {err_str[:40]}..."


# ── Option A: Pre-Trade Sentiment Analysis ───────────────────────────────────

async def fetch_news_headlines(symbol: str) -> list[str]:
    """
    Fetch news headlines from Yahoo Finance RSS.
    No key needed, filters by keyword where possible.
    """
    try:
        url = "https://finance.yahoo.com/news/rss"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        
        # Map symbol to keywords for local filtering
        keywords = {
            "XAUUSD": ["gold", "xau", "fed", "inflation", "cpi", "rate", "bond", "yield"],
            "EURUSD": ["euro", "eur", "ecb", "europe", "rate", "fed", "inflation"],
            "GBPUSD": ["pound", "gbp", "boe", "britain", "uk", "inflation"],
            "USDJPY": ["yen", "jpy", "boj", "japan", "yield"],
            "USDCAD": ["cad", "canada", "oil", "rate"],
            "AUDUSD": ["aud", "australia", "rba", "china"],
        }
        kws = keywords.get(symbol.upper(), [symbol.lower()])
        
        all_headlines = []
        for item in root.findall(".//item"):
            title_node = item.find("title")
            if title_node is not None and title_node.text:
                all_headlines.append(title_node.text.strip())

        # Filter headlines containing any of our keywords
        filtered = [h for h in all_headlines if any(kw in h.lower() for kw in kws)]
        
        # Return filtered headlines, fallback to top 5 general headlines if none match
        headlines = (filtered or all_headlines)[:5]
        log.debug("Yahoo news for %s: %d headlines", symbol, len(headlines))
        return headlines
    except Exception as e:
        log.warning("Yahoo news fetch failed: %s", e)
        return [f"No recent news found for {symbol} due to connection error."]


async def analyze_pre_trade_sentiment(symbol: str, direction: str) -> dict:
    """
    Ask the AI to analyze MT5 news and return a sentiment adjustment.
    Returns dict: sentiment, confidence, score_adjustment, summary
    """
    headlines = await fetch_news_headlines(symbol)

    prompt = f"""You are an expert Forex market analyst integrated into an automated trading bot.

A trade signal has been detected:
- Symbol: {symbol}
- Proposed Direction: {direction}
- Recent market news (last 12h):
{chr(10).join(f"  - {h}" for h in headlines)}

Analyze if this news SUPPORTS or CONFLICTS with the proposed {direction} trade on {symbol}.
Return ONLY a valid JSON object:
{{
  "sentiment": "BULLISH" or "BEARISH" or "NEUTRAL",
  "confidence": 0.0 to 1.0,
  "score_adjustment": number between -20 and +20,
  "summary": "One concise sentence explaining your reasoning"
}}

Rules:
- score_adjustment > 0 means news SUPPORTS the trade direction
- score_adjustment < 0 means news CONFLICTS with the trade
- If news is irrelevant or unclear, return 0
- Only return the JSON, nothing else."""

    try:
        text = await asyncio.wait_for(_call_ai(prompt), timeout=10.0)
        result = json.loads(_strip_json(text))
        log.info(
            "AI Pre-Trade [%s %s]: %s adj=%+.1f — %s",
            symbol, direction,
            result.get("sentiment"), result.get("score_adjustment"), result.get("summary")
        )
        return result
    except asyncio.TimeoutError:
        log.warning("AI pre-trade analysis timed out for %s", symbol)
        return {"sentiment": "NEUTRAL", "confidence": 0.5, "score_adjustment": 0.0, "summary": "AI timed out."}
    except Exception as e:
        log.warning("AI pre-trade analysis failed: %s", e)
        return {"sentiment": "NEUTRAL", "confidence": 0.5, "score_adjustment": 0.0, "summary": f"AI error: {_clean_ai_error(e)}"}


# ── Option B: Post-Trade Review ───────────────────────────────────────────────

async def analyze_post_trade(trade_data: dict) -> str:
    """Ask the AI to write a post-mortem analysis of a closed trade."""
    outcome = "WON" if trade_data.get("pnl_usd", 0) >= 0 else "LOST"

    prompt = f"""You are an expert Forex trading coach reviewing a completed trade.

Trade Details:
- Symbol: {trade_data.get('symbol')} | Direction: {trade_data.get('direction')}
- Entry: {trade_data.get('open_price')} | Exit: {trade_data.get('close_price')}
- P&L: ${trade_data.get('pnl_usd', 0):.2f} ({trade_data.get('pips', 0):.1f} pips)
- Closed by: {trade_data.get('close_reason', 'UNKNOWN')}
- Signal Score: {trade_data.get('signal_score', 'N/A')}/100
- Outcome: {outcome}

Write a concise 3-sentence coaching analysis:
1. Was the {trade_data.get('signal_score', 'N/A')}/100 signal score appropriate for this trade?
2. What does the exit via {trade_data.get('close_reason')} tell us about risk management?
3. One specific, actionable improvement for future similar trades.

Professional tone, plain text only, no bullet points."""

    try:
        result = await asyncio.wait_for(_call_ai(prompt), timeout=15.0)
        log.info("AI Post-Trade review generated for %s", trade_data.get("symbol"))
        return result
    except asyncio.TimeoutError:
        return "AI post-mortem timed out — trade was recorded without analysis."
    except Exception as e:
        log.warning("AI post-trade analysis failed: %s", e)
        return f"AI analysis unavailable: {_clean_ai_error(e)}"


async def test_ai_connection(provider: str, model: str, api_key: str) -> dict:
    """Test AI provider connection with a short test prompt."""
    if not api_key or api_key.startswith("Key set"):
        from src.db.repository import get_setting
        api_key = get_setting("ai_api_key", "")
        
    if not api_key:
        return {"success": False, "error": "No API key provided"}
        
    prompt = "Respond with exactly the word 'SUCCESS' in uppercase, nothing else."
    
    try:
        provider = provider.lower()
        if provider == "gemini":
            text = await asyncio.wait_for(_call_gemini(prompt, api_key, model), timeout=15.0)
        elif provider == "openai":
            text = await asyncio.wait_for(_call_openai(prompt, api_key, model), timeout=15.0)
        elif provider == "openrouter":
            text = await asyncio.wait_for(_call_openai(prompt, api_key, model, base_url="https://openrouter.ai/api/v1"), timeout=25.0)
        elif provider == "anthropic":
            text = await asyncio.wait_for(_call_anthropic(prompt, api_key, model), timeout=15.0)
        else:
            return {"success": False, "error": f"Unknown provider: {provider}"}
            
        return {"success": True, "response": text.strip()}
    except Exception as e:
        log.exception("AI test connection failed")
        return {"success": False, "error": _clean_ai_error(e)}

