"""Versioned prompts: first use seeds v1 as active; existing active prompt is reused."""

import pytest

from app.models import PromptVersion
from app.services.prompts import ensure_active_prompt

pytestmark = pytest.mark.db


def test_first_use_creates_active_version_1(db_session) -> None:
    prompt = ensure_active_prompt(db_session, "generator", "Be clear.")
    assert (prompt.version, prompt.status, prompt.content) == (1, "active", "Be clear.")
    assert prompt.activated_at is not None


def test_existing_active_prompt_is_reused(db_session) -> None:
    first = ensure_active_prompt(db_session, "generator", "v1 text")
    again = ensure_active_prompt(db_session, "generator", "a different default")
    assert again.id == first.id
    assert again.content == "v1 text"


def test_new_version_number_follows_history(db_session) -> None:
    db_session.add(PromptVersion(component="generator", version=3, content="old", status="retired"))
    db_session.flush()
    assert ensure_active_prompt(db_session, "generator", "fresh").version == 4
