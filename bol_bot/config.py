"""Centralised configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime settings. Read from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- credentials ---
    bol_bot_token: str = Field(default="", alias="BOL_BOT_TOKEN")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(
        default="claude-3-5-sonnet-20241022", alias="ANTHROPIC_MODEL"
    )

    # --- logging ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_file: str = Field(default="", alias="LOG_FILE")

    # --- storage ---
    db_path: str = Field(default="data/bol_bot.db", alias="DB_PATH")
    cache_dir: str = Field(default="data/cache", alias="CACHE_DIR")
    enable_cache: bool = Field(default=True, alias="ENABLE_CACHE")

    # --- rate limiting ---
    rate_limit_per_minute: int = Field(default=10, alias="RATE_LIMIT_PER_MINUTE")
    rate_limit_per_day: int = Field(default=100, alias="RATE_LIMIT_PER_DAY")

    # --- access control ---
    admin_ids: List[int] = Field(default_factory=list, alias="ADMIN_IDS")
    whitelist_mode: bool = Field(default=False, alias="WHITELIST_MODE")
    allowed_user_ids: List[int] = Field(default_factory=list, alias="ALLOWED_USER_IDS")

    # --- UX ---
    default_language: str = Field(default="uz", alias="DEFAULT_LANGUAGE")
    max_file_size_mb: int = Field(default=20, alias="MAX_FILE_SIZE_MB")

    # --- engines ---
    tesseract_lang: str = Field(default="eng", alias="TESSERACT_LANG")
    enable_vision: bool = Field(default=True, alias="ENABLE_VISION")

    # --- monitoring ---
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    @field_validator("admin_ids", "allowed_user_ids", mode="before")
    @classmethod
    def _parse_int_list(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return [int(x) for x in v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    def ensure_dirs(self) -> None:
        """Create data/log directories if they don't exist."""
        for p in (self.db_path, self.cache_dir, self.log_file):
            if not p:
                continue
            Path(p).parent.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def reset_settings_for_tests() -> None:
    """Allow tests to reload env-based settings."""
    global _settings
    _settings = None
