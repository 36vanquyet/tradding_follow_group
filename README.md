# GroupTrade Bot

This bot does five things:

1. Listen to Telegram channel/group signals with Telethon.
2. Parse futures signals and filter them through AI.
3. Calculate isolated futures leverage from the stop loss distance, then place entry, SL, TP1 and TP2 on Bybit.
4. Save signal, order and PnL history in SQLite.
5. Use OpenAI to normalize Telegram messages into JSON, with regex fallback.
6. Save Telegram message receive/parse/skip/error state in JSON.
7. Show a localhost dashboard and accept Telegram control commands.

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
   - `TELEGRAM_MESSAGE_STORE_PATH` if you want to move the JSON file
   - `LLM_PROVIDER=groq`
   - `GROQ_API_KEY` and optionally `GROQ_MODEL`
   - `BYBIT_API_KEY`, `BYBIT_API_SECRET`
   - `OPENAI_API_KEY` only if you want fallback OpenAI support
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

Run without reload for scheduled use:

```powershell
.\scripts\start_bot.ps1
```

If you run it manually from PowerShell, use:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_bot.ps1 -Silent
```

If PowerShell execution policy blocks `.ps1` files, use the `.cmd` wrappers:

```powershell
.\scripts\start_bot.cmd
.\scripts\install_task.cmd
.\scripts\remove_task.cmd
```

The `.cmd` wrappers now launch PowerShell hidden and `start_bot.cmd` runs the bot in silent background mode by default.

Or double-click `run.bat` from the project root.

Run silently in the background:

```powershell
.\scripts\start_bot.ps1 -Silent
```

Install a Windows scheduled task that starts the bot at Windows startup:

```powershell
.\scripts\install_task.ps1
```

If you want logon instead, pass:

```powershell
.\scripts\install_task.ps1 -Trigger AtLogOn
```

Remove the scheduled task:

```powershell
.\scripts\remove_task.ps1
```

Scheduled task notes:

- The task itself does not write app logs to a file unless you configure redirection or task history.
- The default scheduled setup now runs `start_bot.ps1 -Silent`, which starts Uvicorn hidden and writes stdout/stderr to `logs/bot.out.log` and `logs/bot.err.log`.
- `AtStartup` requires running `install_task.ps1` as Administrator.
- `AtLogOn` works without admin rights.
- If you want debugging output later, run `.\scripts\start_bot.ps1` manually without `-Silent`.

Dashboard:

- `http://127.0.0.1:8080`

Telegram message tracking:

- The dashboard now shows each Telegram message with `RECEIVED`, `PARSED`, `SKIPPED`, or `ERROR` status.
- The raw message state is stored in the JSON file configured by `TELEGRAM_MESSAGE_STORE_PATH`.
- Groq is used first to normalize messages into JSON and evaluate signals, then regex is used as a fallback if the model is unavailable or the payload is invalid.

API:

- `GET /api/summary`
- `GET /api/signals`
- `GET /api/orders`
- `GET /api/messages`
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
- Manual close instructions like `đóng sớm ARB` are detected and only close the symbol if an open position exists.
- Test on Bybit testnet before using real funds.
