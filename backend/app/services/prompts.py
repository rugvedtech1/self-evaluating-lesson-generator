"""Versioned prompts (system-wide; no user data): creation, validation states, activation, rollback.

Statuses: draft -> validating -> active | rejected ; active -> retired ; retired -> active (rollback).
A database index guarantees at most ONE active version per component.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidOperationError
from app.models import PromptVersion


def get_active_prompt(db: Session, component: str) -> PromptVersion | None:
    return db.scalar(select(PromptVersion).where(PromptVersion.component == component,
                                                 PromptVersion.status == "active"))


def list_prompt_versions(db: Session, component: str) -> list[PromptVersion]:
    return list(db.scalars(select(PromptVersion).where(PromptVersion.component == component)
                           .order_by(PromptVersion.version.desc())))


def _next_version(db: Session, component: str) -> int:
    return (db.scalar(select(func.max(PromptVersion.version)).where(PromptVersion.component == component)) or 0) + 1


def ensure_active_prompt(db: Session, component: str, default_content: str) -> PromptVersion:
    """Return the active prompt; on first use, store the code default as the next version and activate it."""
    active = get_active_prompt(db, component)
    if active is not None:
        return active
    prompt = PromptVersion(
        component=component, version=_next_version(db, component), content=default_content, status="active",
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


def create_candidate_prompt(db: Session, component: str, content: str, *, parent: PromptVersion,
                            change_reason: str) -> PromptVersion:
    candidate = PromptVersion(component=component, version=_next_version(db, component), content=content,
                              status="validating", parent_version_id=parent.id, change_reason=change_reason)
    db.add(candidate)
    db.flush()
    return candidate


def activate_prompt(db: Session, candidate: PromptVersion) -> PromptVersion:
    """Only a validated candidate (or a previously active, retired version) may become active."""
    if candidate.status not in ("validating", "retired"):
        raise InvalidOperationError(f"A '{candidate.status}' prompt version cannot be activated.")
    current = get_active_prompt(db, candidate.component)
    if current is not None and current.id != candidate.id:
        current.status = "retired"
        db.flush()  # free the "one active" slot before taking it
    candidate.status = "active"
    candidate.activated_at = datetime.now(timezone.utc)
    db.flush()
    return candidate


def reject_prompt(db: Session, candidate: PromptVersion) -> PromptVersion:
    candidate.status = "rejected"
    db.flush()
    return candidate


def rollback_prompt(db: Session, component: str, to_version: int | None = None) -> PromptVersion:
    """Re-activate an earlier validated version (default: the one before the current)."""
    current = get_active_prompt(db, component)
    if current is None:
        raise InvalidOperationError("There is no active prompt to roll back.")
    if to_version is None:
        target = db.get(PromptVersion, current.parent_version_id) if current.parent_version_id else None
        if target is None or target.status != "retired":
            target = db.scalar(select(PromptVersion).where(
                PromptVersion.component == component, PromptVersion.status == "retired",
                PromptVersion.version < current.version).order_by(PromptVersion.version.desc()).limit(1))
    else:
        target = db.scalar(select(PromptVersion).where(PromptVersion.component == component,
                                                       PromptVersion.version == to_version))
    if target is None:
        raise InvalidOperationError("There is no earlier validated version to roll back to.")
    if target.id == current.id:
        raise InvalidOperationError("That version is already active.")
    if target.status != "retired":
        raise InvalidOperationError(f"Version {target.version} is '{target.status}' and was never validated "
                                    "as active, so it cannot be restored.")
    return activate_prompt(db, target)
