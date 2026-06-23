"""
scratch/test_signal_channel.py
───────────────────────────────
Quick manual verification script for the Telegram signal channel.

Usage:
  1. Add your bot to the group/channel as admin.
  2. Send ANY message in the group (to make it appear in bot updates).
  3. Run:  python scratch/test_signal_channel.py

The script will:
  - Auto-detect your group chat ID from recent bot updates
  - Send a mock OPEN signal and a mock CLOSE signal to the group
  - Print both formatted messages to console so you can verify the format

Set TELEGRAM_SIGNAL_CHANNEL_ID in .env (or pass as arg) to skip auto-detect.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Force UTF-8 output on Windows so emoji in print() don't crash
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Either read from env or pass as CLI arg: python test_signal_channel.py -100123456789
CHANNEL_ID = os.environ.get("TELEGRAM_SIGNAL_CHANNEL_ID", "")
if len(sys.argv) > 1:
    CHANNEL_ID = sys.argv[1]


async def get_updates(token: str) -> list[dict]:
    """Fetch recent updates from Telegram to find the group chat ID."""
    import httpx
    url = f"https://api.telegram.org/bot{token}/getUpdates?limit=20&timeout=0"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url)
        data = r.json()
    if not data.get("ok"):
        return []
    return data.get("result", [])


async def find_group_chats(token: str) -> list[dict]:
    """Return a list of {id, title} for all group/channel chats visible in recent updates."""
    updates = await get_updates(token)
    seen = {}
    for upd in updates:
        chat = None
        for key in ("message", "channel_post", "edited_message", "my_chat_member", "chat_member"):
            if key in upd:
                chat = upd[key].get("chat", {})
                break
        if chat and chat.get("type") in ("group", "supergroup", "channel"):
            cid = chat["id"]
            if cid not in seen:
                seen[cid] = chat.get("title", str(cid))
    return [{"id": k, "title": v} for k, v in seen.items()]


async def send_message(token: str, chat_id: str | int, text: str) -> dict:
    """Send a Telegram HTML message. Returns the API response dict."""
    import httpx
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, json=payload)
    return r.json()


async def main():
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    global CHANNEL_ID

    # ── Auto-detect group chat ID ─────────────────────────────────────────────
    if not CHANNEL_ID:
        print("🔍 No TELEGRAM_SIGNAL_CHANNEL_ID set — scanning recent bot updates...")
        groups = await find_group_chats(BOT_TOKEN)
        if not groups:
            print("\n❌ No group/channel found in recent bot updates.")
            print("\n📋 Steps to fix:")
            print("   1. Make sure the bot is added to the group as an admin.")
            print("   2. Send ANY message in the group (e.g. 'test').")
            print("   3. Run this script again within ~5 minutes.")
            print("\nAlternatively, pass the chat ID directly:")
            print("   python scratch/test_signal_channel.py -1001234567890")
            sys.exit(1)
        elif len(groups) == 1:
            CHANNEL_ID = groups[0]["id"]
            print(f"✅ Found group: [{CHANNEL_ID}] {groups[0]['title']}")
        else:
            print("\nFound multiple groups/channels — pick one:\n")
            for i, g in enumerate(groups):
                print(f"  [{i}]  {g['id']:>20}   {g['title']}")
            choice = input("\nEnter number: ").strip()
            CHANNEL_ID = groups[int(choice)]["id"]

        print(f"\n💡 TIP: Add this to your .env to skip auto-detect next time:")
        print(f"   TELEGRAM_SIGNAL_CHANNEL_ID={CHANNEL_ID}")
    else:
        print(f"📡 Using channel ID from env/arg: {CHANNEL_ID}")

    # ── Build test messages ───────────────────────────────────────────────────
    from src.telegram.signal_channel import format_signal_open, format_signal_close

    open_msg = format_signal_open(
        symbol="XAUUSD",
        direction="BUY",
        entry_price=2312.50,
        sl_price=2298.20,
        tp_price=2340.90,
        score=71.2,
        session="LONDON/NY OVERLAP",
    )

    close_msg = format_signal_close(
        symbol="XAUUSD",
        direction="BUY",
        pips=28.6,
        pnl_usd=984.20,
        close_reason="TP",
        score=71.2,
        opened_at=datetime(2026, 6, 19, 9, 14, tzinfo=timezone.utc),
        closed_at=datetime.now(timezone.utc),
    )

    print("\n" + "─" * 60)
    print("📤 OPEN SIGNAL (formatted):\n")
    # Strip HTML for console display
    import re
    def strip_html(s):
        return re.sub(r"<[^>]+>", "", s)
    print(strip_html(open_msg))
    print("\n" + "─" * 60)
    print("📤 CLOSE SIGNAL (formatted):\n")
    print(strip_html(close_msg))
    print("─" * 60)

    # ── Send to Telegram ──────────────────────────────────────────────────────
    print(f"\n📨 Sending OPEN signal to chat {CHANNEL_ID} ...")
    r1 = await send_message(BOT_TOKEN, CHANNEL_ID, open_msg)
    if r1.get("ok"):
        print("   ✅ OPEN signal delivered!")
    else:
        print(f"   ❌ Failed: {r1.get('description', r1)}")

    await asyncio.sleep(1)  # Small delay so messages appear in order

    print(f"📨 Sending CLOSE signal to chat {CHANNEL_ID} ...")
    r2 = await send_message(BOT_TOKEN, CHANNEL_ID, close_msg)
    if r2.get("ok"):
        print("   ✅ CLOSE signal delivered!")
    else:
        print(f"   ❌ Failed: {r2.get('description', r2)}")

    print("\n✅ Done — check your Telegram group now.")

    # ── Also update config.yaml if channel_id is empty ───────────────────────
    config_path = Path(__file__).resolve().parents[1] / "config.yaml"
    with open(config_path) as f:
        yaml_text = f.read()
    if 'channel_id: ""' in yaml_text:
        print(f"\n💡 Your config.yaml still has channel_id: \"\" — update it to:")
        print(f'   channel_id: "{CHANNEL_ID}"')
        print(f"   And set enabled: true to activate live signal broadcasting.")


if __name__ == "__main__":
    asyncio.run(main())
