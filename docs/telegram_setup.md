# Telegram Setup Guide

## Step 1: Create Your Bot via @BotFather

1. Open Telegram and search for **@BotFather**
2. Send `/start`
3. Send `/newbot`
4. Follow the prompts:
   - Enter a display name (e.g. `My FX Bot`)
   - Enter a username (must end in `bot`, e.g. `muneeb_fx_bot`)
5. BotFather will reply with your **bot token** — it looks like:
   ```
   1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```
6. **Copy this token** and add it to your `.env` file:
   ```
   TELEGRAM_BOT_TOKEN=1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```

## Step 2: Get Your Chat ID

1. Start a conversation with your new bot (search its username, press **Start**)
2. Open this URL in a browser (replace with your token):
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":XXXXXXX}` in the JSON response
4. Copy that number and add it to `.env`:
   ```
   TELEGRAM_CHAT_ID=123456789
   ```

> **Tip:** If getUpdates returns empty, send any message to your bot first, then try the URL again.

## Step 3: Test the Connection

```bash
python -m src.telegram.client
```

You should receive a test message in Telegram:
> 🤖 **FX Bot** — Telegram connectivity test passed ✅

## Step 4: Group Notifications (Optional)

To send notifications to a Telegram **group**:
1. Add your bot to the group
2. The chat ID for a group is a **negative number** (e.g. `-100987654321`)
3. Use the same getUpdates URL to find the group's chat ID after adding the bot

## Notification Types

| Event | Message |
|---|---|
| Trade opened | Symbol, direction, lots, SL, TP, score |
| Trade closed | P&L, pips, close reason (TP/SL/trailing) |
| Daily summary | Trades, win rate, net P&L, balance |
| Weekly summary | Win rate, profit factor, drawdown |
| Error alert | Critical bot errors |
| Heartbeat | Daily "bot is alive" at 08:00 UTC |
| Emergency stop | Immediate alert when stop is triggered |
