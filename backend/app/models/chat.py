"""Chats, messages and per-chat learner profiles."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, sql_in, user_fk, uuid_pk

CHAT_STATUSES = ("intake", "awaiting_confirmation", "generating", "completed", "failed")
MESSAGE_ROLES = ("user", "assistant", "system")


class Chat(TimestampMixin, Base):
    __tablename__ = "chats"
    __table_args__ = (
        CheckConstraint(sql_in("status", CHAT_STATUSES), name="status_valid"),
        Index("ix_chats_user_id_updated_at", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = user_fk()
    title: Mapped[str] = mapped_column(Text, nullable=False, default="New chat", server_default="New chat")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="intake", server_default="intake")


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(sql_in("role", MESSAGE_ROLES), name="role_valid"),
        Index("ix_messages_chat_id_created_at", "chat_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    chat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = user_fk()
    role: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, default="chat", server_default="chat")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # clock_timestamp(): unlike now(), differs for rows inserted in the same transaction.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )


class ChatProfile(TimestampMixin, Base):
    """Learner profile collected by the Intake Assistant. Exactly one per chat."""

    __tablename__ = "chat_profiles"

    id: Mapped[uuid.UUID] = uuid_pk()
    chat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    user_id: Mapped[uuid.UUID] = user_fk()
    topic: Mapped[str | None] = mapped_column(Text)
    education_level: Mapped[str | None] = mapped_column(Text)
    english_proficiency: Mapped[str | None] = mapped_column(Text)
    technical_background: Mapped[str | None] = mapped_column(Text)
    ai_knowledge: Mapped[str | None] = mapped_column(Text)
    preferred_style: Mapped[str | None] = mapped_column(Text)
    additional_notes: Mapped[str | None] = mapped_column(Text)
    is_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
