"""Tests for settings loading and validation."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

APP_VARS = ("APP_NAME", "APP_VERSION", "APP_ENV", "LOG_LEVEL",
            "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "DATABASE_URL")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for var in APP_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


def test_defaults_without_env_file(clean_env: pytest.MonkeyPatch) -> None:
    settings = Settings(_env_file=None)  # ignore the developer's real .env
    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.database_url is None


def test_environment_variable_overrides_default(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("LOG_LEVEL", "DEBUG")
    assert Settings(_env_file=None).log_level == "DEBUG"


def test_invalid_app_env_is_rejected(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("APP_ENV", "prodution")  # deliberate typo
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secrets_are_masked_when_printed(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("DATABASE_URL", "postgresql+psycopg://u:supersecret@h:5432/db")
    clean_env.setenv("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_topsecret")
    settings = Settings(_env_file=None)
    assert "supersecret" not in repr(settings)
    assert "topsecret" not in repr(settings)
    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().endswith("/db")
