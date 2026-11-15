"""System-wide learning memory. Contains NO user identifiers or user content."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, sql_in, uuid_pk

PROMPT_COMPONENTS = ("intake", "generator", "evaluator")
PROMPT_STATUSES = ("draft", "validating", "active", "retired", "rejected")
FAILURE_PATTERN_STATUSES = ("open", "addressed", "dismissed")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint("component", "version", name="uq_prompt_versions_component_version"),
        CheckConstraint(sql_in("component", PROMPT_COMPONENTS), name="component_valid"),
        CheckConstraint(sql_in("status", PROMPT_STATUSES), name="status_valid"),
        CheckConstraint("version >= 1", name="version_positive"),
        # At most ONE active prompt per component (enables safe activation + rollback).
        Index("ux_prompt_versions_one_active", "component", unique=True,
              postgresql_where=text("status = 'active'")),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    component: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft", server_default="draft")
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("prompt_versions.id", ondelete="SET NULL")
    )
    change_reason: Mapped[str | None] = mapped_column(Text)
    validation_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FailurePattern(Base):
    __tablename__ = "failure_patterns"
    __table_args__ = (
        UniqueConstraint("criterion", "pattern_key", name="uq_failure_patterns_criterion_pattern_key"),
        CheckConstraint(sql_in("status", FAILURE_PATTERN_STATUSES), name="status_valid"),
        CheckConstraint("occurrence_count >= 0", name="occurrence_count_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    criterion: Mapped[str] = mapped_column(Text, nullable=False)
    pattern_key: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="open", server_default="open")
    resolved_by_prompt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("prompt_versions.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
