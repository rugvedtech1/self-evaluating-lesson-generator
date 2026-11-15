"""Frontend settings (where the backend lives, request timeouts)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# frontend/services/settings.py -> parents: [0]=services, [1]=frontend, [2]=project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FrontendSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds backend variables; ignore them here
    )

    backend_url: str = "http://localhost:8000"
    request_timeout_seconds: float = 10.0


@lru_cache
def get_frontend_settings() -> FrontendSettings:
    return FrontendSettings()
