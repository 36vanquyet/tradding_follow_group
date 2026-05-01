from functools import lru_cache
from typing import List

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "GroupTrade Bot"
    app_host: str = "127.0.0.1"
    app_port: int = 8080
    database_url: str = "sqlite:///./grouptrade.db"
    web_base_url: str = "http://127.0.0.1:8080"
    telegram_message_store_path: str = "./telegram_messages.json"
    llm_provider: str = "groq"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_name: str = "grouptrade_listener"
    telegram_source_chat_ids: str = ""
    telegram_bot_token: str = ""
    telegram_notify_chat_id: str = ""
    telegram_notify_raw_messages: bool = True

    bybit_api_key: str = ""
    bybit_api_secret: str = ""
    bybit_testnet: bool = True
    bybit_category: str = "linear"
    bybit_account_type: str = "UNIFIED"
    bybit_recv_window_ms: int = 20000
    bybit_timestamp_safety_ms: int = 5000
    bybit_timestamp_safety_step_ms: int = 1000
    bybit_timestamp_safety_max_ms: int = 15000
    default_quote_asset: str = "USDT"
    max_signal_price_deviation_pct: float = 0.35
    fixed_margin_usdt: float = 25.0
    min_leverage: int = 1
    max_leverage: int = 25
    target_sl_loss_pct: float = 0.32
    tp1_ratio: float = 0.5
    tp2_ratio: float = 0.5

    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    ai_auto_approve: bool = True
    ai_min_confidence: float = 0.55

    sync_interval_seconds: int = 20

    @computed_field
    @property
    def source_chat_ids(self) -> List[int]:
        raw = [value.strip() for value in self.telegram_source_chat_ids.split(",") if value.strip()]
        return [int(value) for value in raw]


@lru_cache
def get_settings() -> Settings:
    return Settings()
