# GroupTrade Bot

This bot does five things:

1. Listen to Telegram channel/group signals with Telethon.
2. Parse futures signals and filter them through AI.
3. Calculate isolated futures leverage from the stop loss distance, then place entry, SL, TP1 and TP2 on Bybit.
4. Save signal, order and PnL history in SQLite.
5. Show a localhost dashboard and accept Telegram control commands.

## Risk model

Experts usually send only `Entry`, `SL`, `TP1`, `TP2`. They do not send margin or leverage.

This project now calculates them automatically:

- `FIXED_MARGIN_USDT`: margin allocated per trade.
- `TARGET_SL_LOSS_PCT`: target loss at stop loss as a fraction of margin. Example `0.32` means about 32% loss of margin when SL is hit.
- `MIN_LEVERAGE` / `MAX_LEVERAGE`: clamp range for leverage.
- `BYBIT_RECV_WINDOW_MS`: extra time window for Bybit requests if your machine clock drifts.
- `BYBIT_TIMESTAMP_SAFETY_MS`: base safety delay subtracted from request timestamps.
- `BYBIT_TIMESTAMP_SAFETY_STEP_MS`: how much to increase safety after a timestamp error.
- `BYBIT_TIMESTAMP_SAFETY_MAX_MS`: maximum safety offset used by the bot.
- `BYBIT_ACCOUNT_TYPE`: `UNIFIED` or `CONTRACT`, used for wallet balance queries.

Formula:

```text
stop_loss_pct = abs(entry - stop_loss) / entry
leverage = floor(TARGET_SL_LOSS_PCT / stop_loss_pct)
position_notional = FIXED_MARGIN_USDT * leverage
qty = position_notional / entry
```

Example:

```text
PAIR:  #APT
TYPE:  BUY
Entry: 0.9357
SL: 0.9076
```

Then:

- stop loss distance is about `3.00%`
- if target stop loss is about `32%` of margin, leverage becomes about `10x`
- with `FIXED_MARGIN_USDT=25`, position notional is about `250 USDT`

The bot also attempts to switch Bybit to isolated mode before placing the order.

## Setup

1. Copy `.env.example` to `.env`.
2. Fill:
   - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`
   - `TELEGRAM_SOURCE_CHAT_IDS`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFY_CHAT_ID`
   - `BYBIT_API_KEY`, `BYBIT_API_SECRET`
   - `OPENAI_API_KEY` if you want real AI evaluation
3. Start with `BYBIT_TESTNET=true`.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Run

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

Dashboard:

- `http://127.0.0.1:8080`

API:

- `GET /api/summary`
- `GET /api/signals`
- `GET /api/orders`
- `GET /health`

## Telegram commands

- `/help`
- `/ping`
- `/status`
- `/orders`
- `/positions`
- `/balance`
- `/sync`
- `/close BTCUSDT`
- `/closeall`
- `/cancel BTCUSDT`
- `/cancelall`

## Notes

- The app auto-adds new SQLite columns for `margin_usdt`, `leverage`, `stop_loss_pct`, `estimated_sl_loss_pct`.
- This code assumes Bybit `linear` USDT perpetual and one-way position mode.
- Different expert formats can be supported by extending `app/services/signal_parser.py`.
- Test on Bybit testnet before using real funds.
