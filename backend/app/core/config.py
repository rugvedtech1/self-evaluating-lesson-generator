"""Application settings loaded from environment variables / the project .env file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents: [0]=core, [1]=app, [2]=backend, [3]=project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Typed, validated backend configuration.

    Priority: real environment variables > .env file > defaults below.
    Secrets use SecretStr so they are masked if the object is ever printed or logged.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env also holds frontend/test variables; ignore them here
    )

    app_name: str = "Lesson Content Generator API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Supabase (optional at import time; required by the features that use them)
    supabase_url: str | None = None
    supabase_publishable_key: SecretStr | None = None
    database_url: SecretStr | None = None

    # Authentication
    jwt_audience: str = "authenticated"
    auth_request_timeout_seconds: float = 10.0

    # LLM: provider and models are configuration, not code
    llm_provider: str = "openai"
    openai_api_key: SecretStr | None = None
    intake_model: str = "gpt-4o-mini"
    generator_model: str = "gpt-4.1-mini"
    evaluator_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    generator_max_tokens: int = 4000  # caps lesson length and cost
    evaluator_max_tokens: int = 3000  # caps evaluation report size and cost
    recover_runs_on_startup: bool = False  # resume interrupted lesson runs when the API starts

    @property
    def supabase_auth_url(self) -> str | None:
        """Base URL of Supabase Auth; also the expected JWT issuer (`iss` claim)."""
        if not self.supabase_url:
            return None
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    """Return one shared Settings instance (read the environment only once)."""
    return Settings()
