"""LangGraph workflow for one lesson run.

Step 4:  START -> load_context -> generate_lesson -(ok)-> save_version -> END
                                                  \\-(error)-> mark_error -> END
Step 5/6 will add: evaluate -> decide -> (regenerate | approve | reject).
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core.exceptions import LLMError
from app.generator.llm import LessonGenerator
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.generator.schemas import GenerationRequest
from app.models import PromptVersion
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service
from app.services import lessons as lesson_service
from app.topics.registry import get_topic

TECHNICAL_FAILURE_MESSAGE = (
    "Sorry, I couldn't write your lesson because of a technical problem with the AI service. "
    "This is not a judgement of your lesson. Please click **Try again**."
)


class LessonState(TypedDict, total=False):
    """Shared workflow state. Plain JSON-friendly values only (safe, inspectable checkpoints)."""

    run_id: str
    user_id: str
    chat_id: str
    topic: str
    topic_key: str
    learner_profile: dict[str, str | None]
    instructions: str
    prompt_version_id: str | None
    lesson_title: str
    lesson_markdown: str
    change_summary: str | None
    attempt_number: int
    lesson_version_id: str
    error: str | None


@dataclass(frozen=True)
class LessonWorkflowDeps:
    session_scope: Callable[[], AbstractContextManager[Session]]  # one short DB transaction per node
    generator: LessonGenerator


def record_generation_failure(db: Session, user_id: uuid.UUID, run_id: uuid.UUID, error: str) -> None:
    """Mark the run as a TECHNICAL error and tell the learner (shared by the graph and the crash handler)."""
    run = lesson_service.mark_lesson_run_error(db, user_id, run_id, error)
    chat = chat_service.get_chat(db, user_id, run.chat_id)
    chat.status = "failed"
    chat_service.add_message(db, user_id, run.chat_id, role="assistant", kind="lesson_error",
                             content=TECHNICAL_FAILURE_MESSAGE, payload={"run_id": str(run_id)})


def route_after_generation(state: LessonState) -> Literal["save_version", "mark_error"]:
    """Conditional edge: plain Python decides the next node from the state."""
    return "mark_error" if state.get("error") else "save_version"


def build_lesson_graph(deps: LessonWorkflowDeps, checkpointer: Any = None) -> Any:

    def load_context(state: LessonState) -> LessonState:
        user_id, run_id = uuid.UUID(state["user_id"]), uuid.UUID(state["run_id"])
        with deps.session_scope() as db:
            run = lesson_service.get_lesson_run(db, user_id, run_id)
            profile = profile_service.get_learner_profile(db, user_id, run.chat_id)
            prompt = db.get(PromptVersion, run.generator_prompt_version_id) if run.generator_prompt_version_id else None
            return {
                "chat_id": str(run.chat_id),
                "topic": run.topic,
                "topic_key": run.topic_key or "generic",
                "learner_profile": {name: getattr(profile, name, None) if profile else None
                                    for name in profile_service.PROFILE_FIELDS},
                "instructions": prompt.content if prompt else DEFAULT_GENERATOR_INSTRUCTIONS,
                "prompt_version_id": str(prompt.id) if prompt else None,
            }

    def generate_lesson(state: LessonState) -> LessonState:
        # No database transaction is open during this (slow) LLM call.
        request = GenerationRequest(
            topic=state["topic"],
            topic_config=get_topic(state["topic_key"]),
            learner_profile=state["learner_profile"],
            instructions=state["instructions"],
        )
        try:
            draft = deps.generator.generate(request)
        except LLMError as exc:
            return {"error": str(exc)}
        return {"lesson_title": draft.title, "lesson_markdown": draft.lesson_markdown,
                "change_summary": draft.change_summary, "error": None}

    def save_version(state: LessonState) -> LessonState:
        user_id, run_id = uuid.UUID(state["user_id"]), uuid.UUID(state["run_id"])
        with deps.session_scope() as db:
            version = lesson_service.add_lesson_version(
                db, user_id, run_id, content=state["lesson_markdown"], change_summary=state.get("change_summary"),
            )
            chat_service.add_message(
                db, user_id, uuid.UUID(state["chat_id"]), role="assistant", kind="lesson_draft",
                content=f"Your lesson draft is ready: **{state['lesson_title']}** (version {version.attempt_number}).",
                payload={"run_id": state["run_id"], "attempt_number": version.attempt_number},
            )
            return {"attempt_number": version.attempt_number, "lesson_version_id": str(version.id)}

    def mark_error(state: LessonState) -> LessonState:
        with deps.session_scope() as db:
            record_generation_failure(db, uuid.UUID(state["user_id"]), uuid.UUID(state["run_id"]),
                                      state.get("error") or "Unknown technical error.")
        return {}

    builder = StateGraph(LessonState)
    builder.add_node("load_context", load_context)
    builder.add_node("generate_lesson", generate_lesson)
    builder.add_node("save_version", save_version)
    builder.add_node("mark_error", mark_error)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "generate_lesson")
    builder.add_conditional_edges("generate_lesson", route_after_generation,
                                  {"save_version": "save_version", "mark_error": "mark_error"})
    builder.add_edge("save_version", END)
    builder.add_edge("mark_error", END)
    return builder.compile(checkpointer=checkpointer)
