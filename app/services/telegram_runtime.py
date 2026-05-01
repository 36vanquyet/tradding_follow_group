import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telethon import TelegramClient, events

from app.config import Settings
from app.database import SessionLocal
from app.services.order_manager import OrderManager
from app.services.repository import Repository
from app.services.telegram_notifier import TelegramNotifier


class TelegramRuntime:
    def __init__(self, settings: Settings, order_manager: OrderManager, notifier: TelegramNotifier):
        self.settings = settings
        self.order_manager = order_manager
        self.notifier = notifier
        self.listener_client: TelegramClient | None = None
        self.bot_app: Application | None = None
        self.sync_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.settings.telegram_api_id and self.settings.telegram_api_hash and self.settings.source_chat_ids:
            self.listener_client = TelegramClient(
                self.settings.telegram_session_name,
                self.settings.telegram_api_id,
                self.settings.telegram_api_hash,
            )
            await self.listener_client.start()

            @self.listener_client.on(events.NewMessage(chats=self.settings.source_chat_ids))
            async def handler(event):
                raw_message = event.raw_text
                chat = await event.get_chat()
                telegram_message_id = getattr(getattr(event, "message", None), "id", None)
                if telegram_message_id is None:
                    telegram_message_id = getattr(event, "id", None)
                record_id = None
                try:
                    record_id = self.order_manager.record_message_received(
                        source_chat_id=str(event.chat_id),
                        source_chat_name=getattr(chat, "title", str(event.chat_id)),
                        telegram_message_id=telegram_message_id,
                        raw_message=raw_message,
                    )
                except Exception as exc:
                    await self.notifier.send(f"Telegram message store error: {exc}")
                if self.settings.telegram_notify_raw_messages and raw_message.strip():
                    preview = " ".join(raw_message.strip().split())
                    if len(preview) > 140:
                        preview = preview[:137] + "..."
                    await self.notifier.send(
                        f"Telegram event received\n"
                        f"Source: {getattr(chat, 'title', str(event.chat_id))}\n"
                        f"Message ID: {telegram_message_id}\n"
                        f"Preview: {preview}"
                    )
                db = SessionLocal()
                try:
                    await self.order_manager.process_message(
                        db=db,
                        source_chat_id=str(event.chat_id),
                        source_chat_name=getattr(chat, "title", str(event.chat_id)),
                        raw_message=raw_message,
                        message_record_id=record_id,
                    )
                finally:
                    db.close()

        if self.settings.telegram_bot_token:
            self.bot_app = Application.builder().token(self.settings.telegram_bot_token).build()
            self.bot_app.add_handler(CommandHandler("help", self.help_command))
            self.bot_app.add_handler(CommandHandler("ping", self.ping_command))
            self.bot_app.add_handler(CommandHandler("status", self.status_command))
            self.bot_app.add_handler(CommandHandler("orders", self.orders_command))
            self.bot_app.add_handler(CommandHandler("positions", self.positions_command))
            self.bot_app.add_handler(CommandHandler("balance", self.balance_command))
            self.bot_app.add_handler(CommandHandler("sync", self.sync_command))
            self.bot_app.add_handler(CommandHandler("cancel", self.cancel_command))
            self.bot_app.add_handler(CommandHandler("cancelall", self.cancelall_command))
            self.bot_app.add_handler(CommandHandler("close", self.close_command))
            self.bot_app.add_handler(CommandHandler("closeall", self.closeall_command))
            await self.bot_app.initialize()
            await self.bot_app.start()
            await self.bot_app.updater.start_polling()
            await self._notify_boot()

        self.sync_task = asyncio.create_task(self.sync_loop())

    async def stop(self) -> None:
        if self.sync_task:
            self.sync_task.cancel()
        if self.bot_app:
            await self.bot_app.updater.stop()
            await self.bot_app.stop()
            await self.bot_app.shutdown()
        if self.listener_client:
            await self.listener_client.disconnect()

    async def _notify_boot(self) -> None:
        message = self._runtime_status_message(prefix="Bot started")
        await self.notifier.send(message)

    def _runtime_status_message(self, prefix: str = "Status") -> str:
        listener_state = "ON" if self.listener_client else "OFF"
        bot_state = "ON" if self.bot_app else "OFF"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        return (
            f"{prefix}\n"
            f"Time: {now}\n"
            f"Telegram bot: {bot_state}\n"
            f"Telegram listener: {listener_state}\n"
            f"Dashboard: {self.settings.web_base_url}"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = (
            "Commands:\n"
            "/help - show this message\n"
            "/ping - quick bot alive check\n"
            "/status - bot runtime and trade summary\n"
            "/orders - open orders on Bybit\n"
            "/positions - open positions on Bybit\n"
            "/balance - current wallet balance on Bybit\n"
            "/sync - sync closed PnL from Bybit now\n"
            "/close BTCUSDT - close the open position for a symbol\n"
            "/closeall - close all open positions\n"
            "/cancel BTCUSDT - cancel orders for a symbol\n"
            "/cancelall - cancel all open orders"
        )
        await update.message.reply_text(message)

    async def ping_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(self._runtime_status_message(prefix="Pong"))

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        db = SessionLocal()
        try:
            repo = Repository(db)
            summary = repo.summary()
            message = (
                f"{self._runtime_status_message(prefix='Status')}\n"
                f"Signals: {summary['signals']}\n"
                f"Closed PnL: {summary['closed_pnl']:.4f}\n"
                f"Wins: {summary['wins']} | Losses: {summary['losses']}\n"
                f"Dashboard: {self.settings.web_base_url}"
            )
        finally:
            db.close()
        await update.message.reply_text(message)

    async def orders_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        orders = self.order_manager.bybit.get_open_orders()
        if not orders:
            await update.message.reply_text("No open orders.")
            return
        lines = [
            f"{item.get('symbol')} {item.get('side')} qty={item.get('qty')} price={item.get('price')} status={item.get('orderStatus')}"
            for item in orders[:10]
        ]
        await update.message.reply_text("\n".join(lines))

    async def positions_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        positions = [item for item in self.order_manager.bybit.get_positions() if float(item.get("size", 0) or 0) > 0]
        if not positions:
            await update.message.reply_text("No open positions.")
            return
        lines = [
            f"{item.get('symbol')} {item.get('side')} size={item.get('size')} entry={item.get('avgPrice')} pnl={item.get('unrealisedPnl')}"
            for item in positions[:10]
        ]
        await update.message.reply_text("\n".join(lines))

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            balance = self.order_manager.bybit.get_wallet_balance()
        except Exception as exc:
            await update.message.reply_text(f"Failed to fetch balance: {exc}")
            return

        message = (
            f"Account: {balance['account_type']}\n"
            f"Coin: {balance['coin']}\n"
            f"Total equity: {balance['total_equity']:.4f}\n"
            f"Wallet balance: {balance['wallet_balance']:.4f}\n"
            f"Available balance: {balance['available_balance']:.4f}\n"
            f"Coin equity: {balance['coin_equity']:.4f}\n"
            f"Coin wallet balance: {balance['coin_wallet_balance']:.4f}"
        )
        await update.message.reply_text(message)

    async def sync_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        db = SessionLocal()
        try:
            result = self.order_manager.sync_closed_pnl(db)
        except Exception as exc:
            await update.message.reply_text(f"Failed to sync data: {exc}")
            return
        finally:
            db.close()
        await update.message.reply_text(
            "Sync complete\n"
            f"Closed trades fetched: {result['processed']}\n"
            f"Matched local signals: {result['matched']}"
        )

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Dùng: /cancel BTCUSDT")
            return
        symbol = context.args[0].upper()
        db = SessionLocal()
        try:
            message = await self.order_manager.cancel_symbol(db, symbol)
        finally:
            db.close()
        await update.message.reply_text(message)

    async def cancelall_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            result = self.order_manager.bybit.cancel_all_orders()
        except Exception as exc:
            await update.message.reply_text(f"Failed to cancel all orders: {exc}")
            return
        await update.message.reply_text(
            "Cancelled all open orders\n"
            f"Result: {self.order_manager.bybit.dump(result)}"
        )

    async def close_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not context.args:
            await update.message.reply_text("Dùng: /close BTCUSDT")
            return
        symbol = context.args[0].upper()
        try:
            result = self.order_manager.bybit.close_symbol_position(symbol)
        except Exception as exc:
            await update.message.reply_text(f"Failed to close {symbol}: {exc}")
            return
        if not result.get("closed"):
            await update.message.reply_text(f"No open position found for {symbol}")
            return
        await update.message.reply_text(
            f"Closed position for {symbol}\n"
            f"Result: {self.order_manager.bybit.dump(result)}"
        )

    async def closeall_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            result = self.order_manager.bybit.close_all_positions()
        except Exception as exc:
            await update.message.reply_text(f"Failed to close all positions: {exc}")
            return
        await update.message.reply_text(
            "Closed all open positions\n"
            f"Result: {self.order_manager.bybit.dump(result)}"
        )

    async def sync_loop(self) -> None:
        await asyncio.sleep(self.settings.sync_interval_seconds)
        while True:
            db = SessionLocal()
            try:
                self.order_manager.sync_closed_pnl(db)
            except Exception as exc:
                await self.notifier.send(f"Sync error: {exc}")
            finally:
                db.close()
            await asyncio.sleep(self.settings.sync_interval_seconds)
