"""Storage for lesson runs, lesson versions and evaluation reports.

The Python Decision Gate decides WHEN to generate, approve or reject.
This module guarantees that whatever it stores is owned, sequential, consistent and replay-safe.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.models import Evaluation, LessonRun, LessonVersion
from app.services.chats import get_chat

FINISHED_RUN_STATUSES = frozenset({"approved", "rejected", "error"})
ACTIVE_RUN_STATUSES = frozenset({"pending", "running"})


@dataclass(frozen=True)
class AttemptRecord:
    version: LessonVersion
    evaluation: Evaluation | None


@dataclass(frozen=True)
class LessonRunHistory:
    run: LessonRun
    attempts: list[AttemptRecord]


def run_phase(status: str, versions: int, evaluations: int, max_attempts: int) -> tuple[str, int]:
    """What the learner should see now, derived from stored data: (phase, current attempt)."""
    if status in FINISHED_RUN_STATUSES:
        return status, versions
    if versions == 0:
        return "writing", 1
    if versions > evaluations:
        return "evaluating", versions
    return "improving", min(versions + 1, max_attempts)


def create_lesson_run(
    db: Session,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    *,
    topic: str,
    topic_key: str | None = None,
    generator_prompt_version_id: uuid.UUID | None = None,
    evaluator_prompt_version_id: uuid.UUID | None = None,
) -> LessonRun:
    get_chat(db, user_id, chat_id)  # ownership check
    run = LessonRun(
        chat_id=chat_id, user_id=user_id, topic=topic, topic_key=topic_key, status="running",
        generator_prompt_version_id=generator_prompt_version_id,
        evaluator_prompt_version_id=evaluator_prompt_version_id,
    )
    # clock_timestamp(): distinct times even for runs created in one transaction ("latest" stays well defined)
    run.created_at = func.clock_timestamp()
    run.updated_at = func.clock_timestamp()
    db.add(run)
    db.flush()
    return run


def get_lesson_run(db: Session, user_id: uuid.UUID, run_id: uuid.UUID, *, lock: bool = False) -> LessonRun:
    stmt = select(LessonRun).where(LessonRun.id == run_id, LessonRun.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()  # serialise concurrent writers on the same run
    run = db.scalar(stmt)
    if run is None:
        raise NotFoundError("Lesson run not found.")
    return run


def list_lesson_runs(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> list[LessonRun]:
    get_chat(db, user_id, chat_id)
    stmt = (select(LessonRun)
            .where(LessonRun.chat_id == chat_id, LessonRun.user_id == user_id)
            .order_by(LessonRun.created_at.desc()))
    return list(db.scalars(stmt))


def get_latest_lesson_run(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> LessonRun | None:
    runs = list_lesson_runs(db, user_id, chat_id)
    return runs[0] if runs else None


def mark_lesson_run_error(db: Session, user_id: uuid.UUID, run_id: uuid.UUID, error_message: str) -> LessonRun:
    """A TECHNICAL failure (API down, crash). Never used for content-quality rejection. Idempotent."""
    run = get_lesson_run(db, user_id, run_id, lock=True)
    if run.status in FINISHED_RUN_STATUSES:
        return run
    run.status = "error"
    run.error_message = error_message[:1000]
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    return run


def finish_lesson_run(db: Session, user_id: uuid.UUID, run_id: uuid.UUID, *, status: str,
                      final_attempt_number: int) -> tuple[LessonRun, bool]:
    """Record the Decision Gate's final outcome. Returns (run, changed) so replays don't repeat side effects."""
    if status not in ("approved", "rejected"):
        raise ValueError("A run can only finish as 'approved' or 'rejected'.")
    run = get_lesson_run(db, user_id, run_id, lock=True)
    if run.status in FINISHED_RUN_STATUSES:
        return run, False
    run.status = status
    run.final_attempt_number = final_attempt_number
    run.completed_at = datetime.now(timezone.utc)
    db.flush()
    return run, True


def get_version_by_attempt(db: Session, user_id: uuid.UUID, run_id: uuid.UUID,
                           attempt_number: int) -> LessonVersion | None:
    return db.scalar(select(LessonVersion).where(
        LessonVersion.run_id == run_id, LessonVersion.user_id == user_id,
        LessonVersion.attempt_number == attempt_number))


def add_lesson_version(
    db: Session,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    *,
    content: str,
    generator_feedback: str | None = None,
    change_summary: str | None = None,
    expected_attempt: int | None = None,
) -> LessonVersion:
    """Store the next attempt. With expected_attempt, a replay after a crash returns the existing version."""
    run = get_lesson_run(db, user_id, run_id, lock=True)
    if expected_attempt is not None and run.attempt_count >= expected_attempt:
        existing = get_version_by_attempt(db, user_id, run_id, expected_attempt)
        if existing is not None:
            return existing
    if run.status in FINISHED_RUN_STATUSES:
        raise InvalidOperationError("Lesson run is already finished.")
    if run.attempt_count >= run.max_attempts:
        raise InvalidOperationError("Maximum generation attempts reached.")

    attempt_number = run.attempt_count + 1
    if expected_attempt is not None and expected_attempt != attempt_number:
        raise InvalidOperationError("Attempt numbers must be sequential.")
    version = LessonVersion(
        run_id=run.id, user_id=user_id, attempt_number=attempt_number, content=content,
        generator_feedback=generator_feedback, change_summary=change_summary,
    )
    run.attempt_count = attempt_number
    db.add(version)
    db.flush()
    return version


def add_evaluation(
    db: Session,
    user_id: uuid.UUID,
    lesson_version_id: uuid.UUID,
    *,
    overall_status: str,
    criteria_results: list[dict[str, Any]],
    failed_criteria: list[str],
    feedback_for_generator: str | None = None,
) -> Evaluation:
    version = db.scalar(select(LessonVersion).where(LessonVersion.id == lesson_version_id,
                                                    LessonVersion.user_id == user_id))
    if version is None:
        raise NotFoundError("Lesson version not found.")
    existing = db.scalar(select(Evaluation).where(Evaluation.lesson_version_id == version.id))
    if existing is not None:
        return existing  # replay after a crash: already stored
    if overall_status not in ("PASS", "FAIL"):
        raise ValueError("overall_status must be PASS or FAIL.")
    # No partial credit: PASS means zero failures; FAIL means at least one.
    if overall_status == "PASS" and failed_criteria:
        raise ValueError("A PASS evaluation cannot list failed criteria.")
    if overall_status == "FAIL" and not failed_criteria:
        raise ValueError("A FAIL evaluation must list at least one failed criterion.")

    evaluation = Evaluation(
        lesson_version_id=version.id, run_id=version.run_id, user_id=user_id,
        overall_status=overall_status, criteria_results=criteria_results,
        failed_criteria=failed_criteria, feedback_for_generator=feedback_for_generator,
    )
    db.add(evaluation)
    db.flush()
    return evaluation


def get_lesson_run_history(db: Session, user_id: uuid.UUID, run_id: uuid.UUID) -> LessonRunHistory:
    """Everything needed for a rejection log: each attempt and its evaluation, in order."""
    run = get_lesson_run(db, user_id, run_id)
    versions = list(db.scalars(
        select(LessonVersion)
        .where(LessonVersion.run_id == run.id, LessonVersion.user_id == user_id)
        .order_by(LessonVersion.attempt_number)
    ))
    evaluations = {
        e.lesson_version_id: e
        for e in db.scalars(select(Evaluation).where(Evaluation.run_id == run.id,
                                                     Evaluation.user_id == user_id))
    }
    return LessonRunHistory(
        run=run,
        attempts=[AttemptRecord(version=v, evaluation=evaluations.get(v.id)) for v in versions],
    )
