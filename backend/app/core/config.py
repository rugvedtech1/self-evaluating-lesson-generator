"""Application settings loaded from environment variables / the project .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents: [0]=core, [1]=app, [2]=backend, [3]=project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed, validated backend configuration.

    Priority: real environment variables > .env file > defaults below.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds frontend variables; ignore them here
    )

    app_name: str = "Lesson Content Generator API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance (read the environment only once)."""
    return Settings()
