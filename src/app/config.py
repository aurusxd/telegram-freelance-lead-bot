from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = ""
    owner_tg_id: int = 0

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telethon_session_path: Path = Path("./data/telethon.session")

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    github_token: str = ""
    github_username: str = ""

    searxng_base_url: str = "http://searxng:8080"

    sources_file_path: Path = Path("./sources.json")

    database_url: str = "sqlite+aiosqlite:///./data/bot.db"

    log_level: str = "INFO"
    discovery_interval_minutes: int = Field(default=10, ge=1)
    discovery_messages_per_chat: int = Field(default=20, ge=1)
    discovery_queries_per_run: int = Field(default=5, ge=1)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
