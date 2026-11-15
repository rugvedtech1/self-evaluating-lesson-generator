"""Versioned prompts (system-wide; no user data). Step 7 adds validation, activation and rollback."""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PromptVersion


def get_active_prompt(db: Session, component: str) -> PromptVersion | None:
    return db.scalar(select(PromptVersion).where(PromptVersion.component == component,
                                                 PromptVersion.status == "active"))


def ensure_active_prompt(db: Session, component: str, default_content: str) -> PromptVersion:
    """Return the active prompt; on first use, store the code default as the next version and activate it."""
    active = get_active_prompt(db, component)
    if active is not None:
        return active

    latest = db.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.component == component)) or 0
    prompt = PromptVersion(
        component=component, version=latest + 1, content=default_content, status="active",
        change_reason="Initial default prompt", activated_at=datetime.now(timezone.utc),
    )
    try:
        with db.begin_nested():  # savepoint: a concurrent creator may win the unique "one active" index
            db.add(prompt)
            db.flush()
    except IntegrityError:
        active = get_active_prompt(db, component)
        if active is None:
            raise
        return active
    return prompt
