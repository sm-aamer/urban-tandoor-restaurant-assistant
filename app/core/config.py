from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.8-flash"
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = "openrouter/free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chat_memory_ttl_seconds: int = Field(default=1_800, ge=1, le=86_400)
    chat_memory_max_conversations: int = Field(default=1_000, ge=1, le=100_000)
    chat_memory_max_messages: int = Field(default=10, ge=2, le=100)
    chat_memory_max_message_length: int = Field(default=2_000, ge=1, le=2_000)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
