"""Per-chat learner profiles collected by the Intake Assistant."""

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.models import ChatProfile
from app.services.chats import get_chat

PROFILE_FIELDS = (
    "topic", "education_level", "english_proficiency", "technical_background",
    "ai_knowledge", "preferred_style", "additional_notes",
)


def get_learner_profile(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> ChatProfile | None:
    get_chat(db, user_id, chat_id)  # ownership check
    return db.scalar(select(ChatProfile).where(ChatProfile.chat_id == chat_id,
                                               ChatProfile.user_id == user_id))


def upsert_learner_profile(
    db: Session, user_id: uuid.UUID, chat_id: uuid.UUID, updates: Mapping[str, str | None]
) -> ChatProfile:
    """Create or partially update the profile. Any real change requires re-confirmation."""
    unknown = set(updates) - set(PROFILE_FIELDS)
    if unknown:
        raise ValueError(f"Unknown learner profile fields: {sorted(unknown)}")

    profile = get_learner_profile(db, user_id, chat_id)
    if profile is None:
        profile = ChatProfile(chat_id=chat_id, user_id=user_id)
        db.add(profile)

    changed = False
    for field_name, value in updates.items():
        if getattr(profile, field_name) != value:
            setattr(profile, field_name, value)
            changed = True

    if changed and profile.is_confirmed:
        profile.is_confirmed = False
        profile.confirmed_at = None
    db.flush()
    return profile


def confirm_learner_profile(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> ChatProfile:
    profile = get_learner_profile(db, user_id, chat_id)
    if profile is None:
        raise NotFoundError("Learner profile not found.")
    if not profile.topic:
        raise InvalidOperationError("Cannot confirm a learner profile without a topic.")
    profile.is_confirmed = True
    profile.confirmed_at = datetime.now(timezone.utc)
    db.flush()
    return profile
