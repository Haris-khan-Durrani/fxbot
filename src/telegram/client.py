"""
src/telegram/client.py
──────────────────────
Minimal async Telegram sender.
If bot token is missing, logs a warning and disables notifications.
Never crashes the main bot loop.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from src.core.config import load_config
from src.core.logger import get_logger

log = get_logger(__name__)

_bot = None
_chat_id: Optional[str] = None
_enabled: bool = False


def _init_telegram() -> None:
    global _bot, _chat_id, _enabled
    if _bot is not None:
        return

    cfg = load_config()
    token = cfg["env"].get("TELEGRAM_BOT_TOKEN", "")
    _chat_id = cfg["env"].get("TELEGRAM_CHAT_ID", "")

    if not token or not _chat_id:
        log.warning(
            "Telegram not configured (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing). "
            "Notifications disabled."
        )
        _enabled = False
        return

    try:
        from telegram import Bot
        import httpx

        # Support proxy for regions where api.telegram.org is blocked
        proxy_url = cfg["env"].get("TELEGRAM_PROXY_URL", "")
        if proxy_url:
            log.info("Telegram: using proxy %s", proxy_url.split("@")[-1])  # hide credentials
            request_kwargs = httpx.Client(proxy=proxy_url)
        else:
            request_kwargs = None

        _bot = Bot(token=token)
        _enabled = True
        log.info("✅ Telegram bot initialized.")
    except Exception as e:
        log.warning("Failed to initialize Telegram bot: %s", e)
        _enabled = False


def is_enabled() -> bool:
    _init_telegram()
    return _enabled


async def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a Telegram message. Returns True on success.
    Never raises — failures are logged and swallowed.
    """
    _init_telegram()
    if not _enabled or _bot is None:
        return False

    try:
        await _bot.send_message(
            chat_id=_chat_id,
            text=text,
            parse_mode=parse_mode,
        )
        return True
    except Exception as e:
        log.warning("Telegram send_message failed: %s", e)
        return False


async def test_connection() -> bool:
    """Send a test message to verify bot connectivity."""
    _init_telegram()
    if not _enabled:
        return False
    success = await send_message("🤖 <b>FX Bot</b> — Telegram connectivity test passed ✅")
    if success:
        log.info("✅ Telegram test message sent.")
    return success


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[2]))
    from src.core.logger import setup_root_logger
    setup_root_logger()

    async def _test():
        ok = await test_connection()
        print(f"\n{'✅ Telegram OK' if ok else '❌ Telegram failed (check .env)'}")

    asyncio.run(_test())
