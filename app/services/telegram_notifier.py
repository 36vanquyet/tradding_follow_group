from telegram import Bot

from app.config import Settings


class TelegramNotifier:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bot = Bot(token=settings.telegram_bot_token) if settings.telegram_bot_token else None

    async def send(self, message: str) -> None:
        if not self.bot or not self.settings.telegram_notify_chat_id:
            return
        await self.bot.send_message(chat_id=self.settings.telegram_notify_chat_id, text=message)
