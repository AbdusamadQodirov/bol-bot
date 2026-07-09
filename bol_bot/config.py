"""Centralised configuration loaded from environment / .env file."""
from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_int_csv(raw: str) -> List[int]:
    """Parse '123,456' or '123' or '' into a list of ints."""
    if not raw:
        return []
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


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
    # Stored as raw strings to avoid pydantic-settings' JSON-list parsing
    # rejecting bare integers like ADMIN_IDS=2024037771.
    admin_ids_raw: str = Field(default="", alias="ADMIN_IDS")
    whitelist_mode: bool = Field(default=False, alias="WHITELIST_MODE")
    allowed_user_ids_raw: str = Field(default="", alias="ALLOWED_USER_IDS")

    @computed_field
    @property
    def admin_ids(self) -> List[int]:
        return _parse_int_csv(self.admin_ids_raw)

    @computed_field
    @property
    def allowed_user_ids(self) -> List[int]:
        return _parse_int_csv(self.allowed_user_ids_raw)

    # --- UX ---
    default_language: str = Field(default="uz", alias="DEFAULT_LANGUAGE")
    max_file_size_mb: int = Field(default=20, alias="MAX_FILE_SIZE_MB")

    # --- engines ---
    tesseract_lang: str = Field(default="eng", alias="TESSERACT_LANG")
    enable_vision: bool = Field(default=True, alias="ENABLE_VISION")

    # --- monitoring ---
    sentry_dsn: str = Field(default="", alias="SENTRY_DSN")

    def ensure_dirs(self) -> None:
        """Create data/log directories if they don't exist."""
        # db_path / log_file are FILE paths -> create their parent dir.
        for p in (self.db_path, self.log_file):
            if not p:
                continue
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        # cache_dir is a DIRECTORY itself, not a file -> create it directly.
        if self.cache_dir:
            Path(self.cache_dir).mkdir(parents=True, exist_ok=True)


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
