"""Lesson runs, lesson versions and evaluation reports."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, sql_in, user_fk, uuid_pk

MAX_GENERATION_ATTEMPTS = 3
LESSON_RUN_STATUSES = ("pending", "running", "approved", "rejected", "error")
EVALUATION_STATUSES = ("PASS", "FAIL")


class LessonRun(TimestampMixin, Base):
    """One execution of the generate -> evaluate -> (regenerate) loop."""

    __tablename__ = "lesson_runs"
    __table_args__ = (
        CheckConstraint(sql_in("status", LESSON_RUN_STATUSES), name="status_valid"),
        CheckConstraint(f"max_attempts BETWEEN 1 AND {MAX_GENERATION_ATTEMPTS}", name="max_attempts_valid"),
        CheckConstraint("attempt_count BETWEEN 0 AND max_attempts", name="attempt_count_valid"),
        Index("ix_lesson_runs_chat_id", "chat_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    chat_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = user_fk()
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    topic_key: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=MAX_GENERATION_ATTEMPTS, server_default=text(str(MAX_GENERATION_ATTEMPTS))
    )
    generator_prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("prompt_versions.id", ondelete="SET NULL")
    )
    evaluator_prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("prompt_versions.id", ondelete="SET NULL")
    )
    final_attempt_number: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)  # technical failures only
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LessonVersion(Base):
    """One generated lesson (one per attempt)."""

    __tablename__ = "lesson_versions"
    __table_args__ = (
        UniqueConstraint("run_id", "attempt_number", name="uq_lesson_versions_run_id_attempt_number"),
        CheckConstraint(f"attempt_number BETWEEN 1 AND {MAX_GENERATION_ATTEMPTS}", name="attempt_number_valid"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lesson_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = user_fk()
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    generator_feedback: Mapped[str | None] = mapped_column(Text)  # feedback that produced this version
    change_summary: Mapped[str | None] = mapped_column(Text)      # what changed vs previous version
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Evaluation(Base):
    """Structured PASS/FAIL report for one lesson version."""

    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint(sql_in("overall_status", EVALUATION_STATUSES), name="overall_status_valid"),
        Index("ix_evaluations_run_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    lesson_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lesson_versions.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("lesson_runs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = user_fk()
    overall_status: Mapped[str] = mapped_column(Text, nullable=False)
    criteria_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    failed_criteria: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    feedback_for_generator: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
