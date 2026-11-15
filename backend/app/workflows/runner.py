"""Starting lesson runs (inside the HTTP request), executing and resuming the workflow (in the background)."""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.db.session import session_scope as default_session_scope
from app.evaluator.prompts import DEFAULT_EVALUATOR_INSTRUCTIONS
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.models import Chat, LessonRun
from app.services import learner_profiles as profile_service
from app.services import lessons as lesson_service
from app.services.prompts import ensure_active_prompt
from app.topics.registry import match_topic
from app.workflows.lesson_graph import record_generation_failure

logger = logging.getLogger(__name__)
STARTABLE_CHAT_STATUSES = ("generating", "failed", "completed")
NOT_CONFIRMED = "Confirm your learner profile before generating a lesson."


def start_lesson_run(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> LessonRun:
    """Validate and create a run. The chat row is locked so two clicks can't start two runs."""
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id).with_for_update())
    if chat is None:
        raise NotFoundError("Chat not found.")
    if chat.status not in STARTABLE_CHAT_STATUSES:
        raise InvalidOperationError(NOT_CONFIRMED)
    profile = profile_service.get_learner_profile(db, user_id, chat_id)
    if profile is None or not profile.is_confirmed or not profile.topic:
        raise InvalidOperationError(NOT_CONFIRMED)
    latest = lesson_service.get_latest_lesson_run(db, user_id, chat_id)
    if latest is not None and latest.status in lesson_service.ACTIVE_RUN_STATUSES:
        raise InvalidOperationError("A lesson is already being generated for this chat.")
    if latest is not None and latest.status == "approved":
        raise InvalidOperationError("This chat already has an approved lesson. Start a new chat to learn more.")

    generator_prompt = ensure_active_prompt(db, "generator", DEFAULT_GENERATOR_INSTRUCTIONS)
    evaluator_prompt = ensure_active_prompt(db, "evaluator", DEFAULT_EVALUATOR_INSTRUCTIONS)
    run = lesson_service.create_lesson_run(
        db, user_id, chat_id, topic=profile.topic, topic_key=match_topic(profile.topic).key,
        generator_prompt_version_id=generator_prompt.id, evaluator_prompt_version_id=evaluator_prompt.id,
    )
    chat.status = "generating"
    db.flush()
    return run


class LessonWorkflowRunner:
    """Executes (or resumes) the compiled graph for one run. Called from background tasks / recovery."""

    def __init__(self, graph: Any,
                 session_scope: Callable[[], AbstractContextManager[Session]] = default_session_scope) -> None:
        self._graph = graph
        self._session_scope = session_scope

    @staticmethod
    def _config(run_id: uuid.UUID) -> dict:
        return {"configurable": {"thread_id": str(run_id)}}

    def run(self, run_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self._execute(run_id, user_id, lambda: self._graph.invoke(
            {"run_id": str(run_id), "user_id": str(user_id)}, self._config(run_id)))

    def resume(self, run_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Continue an interrupted run from its last checkpoint."""
        def _resume() -> None:
            snapshot = self._graph.get_state(self._config(run_id))
            if snapshot.next:
                logger.info("Resuming lesson workflow from checkpoint",
                            extra={"context": {"run_id": str(run_id), "next": list(snapshot.next)}})
                self._graph.invoke(None, self._config(run_id))
            elif not snapshot.values:
                self._graph.invoke({"run_id": str(run_id), "user_id": str(user_id)}, self._config(run_id))
            else:
                raise RuntimeError("Workflow ended without finalising the run.")
        self._execute(run_id, user_id, _resume)

    def _execute(self, run_id: uuid.UUID, user_id: uuid.UUID, action: Callable[[], None]) -> None:
        context = {"run_id": str(run_id)}
        logger.info("Lesson workflow started", extra={"context": context})
        try:
            action()
            logger.info("Lesson workflow finished", extra={"context": context})
        except Exception:
            # Unexpected crash (bug, DB outage...): still a TECHNICAL failure, never a content verdict.
            logger.exception("Lesson workflow crashed", extra={"context": context})
            try:
                with self._session_scope() as db:
                    record_generation_failure(db, user_id, run_id, "The lesson run was interrupted.")
            except Exception:
                logger.exception("Could not record workflow failure", extra={"context": context})
