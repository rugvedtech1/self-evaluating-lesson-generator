"""LangGraph workflow for one lesson run, with the Python Decision Gate.

START → load_context → generate_lesson ─ok→ save_version → evaluate_lesson ─ok→ save_evaluation ─┐
             ▲              └error→ mark_error → END        └error→ mark_error → END              │
             └──────── regenerate (previous version + evaluator feedback) ◀── decide() ──────────┤
                                                       approve_lesson → END  ◀── PASS            │
                                                       reject_lesson  → END  ◀── FAIL on last ───┘
Each node runs in its own short DB transaction; no transaction is open during LLM calls.
Saving nodes are idempotent, so a run resumed from a checkpoint never duplicates attempts.
"""

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.core.exceptions import LLMError
from app.evaluator.engine import EvaluationRequest
from app.evaluator.prompts import DEFAULT_EVALUATOR_INSTRUCTIONS
from app.evaluator.schemas import EvaluationReport
from app.generator.llm import LessonGenerator
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.generator.schemas import GenerationRequest
from app.models import PromptVersion
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service
from app.services import lessons as lesson_service
from app.topics.registry import get_topic
from app.workflows.decision import decide

logger = logging.getLogger(__name__)

TECHNICAL_FAILURE_MESSAGE = (
    "Sorry, I couldn't finish your lesson because of a technical problem with the AI service. "
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
    generator_instructions: str
    evaluator_instructions: str
    max_attempts: int
    attempt_number: int             # attempt currently being produced / just produced
    lesson_title: str
    lesson_markdown: str
    change_summary: str | None
    generator_feedback: str | None  # feedback this attempt was asked to fix
    lesson_version_id: str
    overall_status: str
    failed_criteria: list[str]
    evaluation: dict[str, Any]
    evaluation_feedback: str | None  # feedback for the NEXT attempt
    error: str | None
    error_stage: str | None


class LessonEvaluatorLike(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport: ...


@dataclass(frozen=True)
class LessonWorkflowDeps:
    session_scope: Callable[[], AbstractContextManager[Session]]  # one short DB transaction per node
    generator: LessonGenerator
    evaluator: LessonEvaluatorLike


def record_generation_failure(db: Session, user_id: uuid.UUID, run_id: uuid.UUID, error: str) -> None:
    """Mark the run as a TECHNICAL error and tell the learner. Does nothing if the run already finished."""
    run = lesson_service.get_lesson_run(db, user_id, run_id)
    if run.status in lesson_service.FINISHED_RUN_STATUSES:
        return
    lesson_service.mark_lesson_run_error(db, user_id, run_id, error)
    chat = chat_service.get_chat(db, user_id, run.chat_id)
    chat.status = "failed"
    chat_service.add_message(db, user_id, run.chat_id, role="assistant", kind="lesson_error",
                             content=TECHNICAL_FAILURE_MESSAGE, payload={"run_id": str(run_id)})


def route_after_generation(state: LessonState) -> Literal["save_version", "mark_error"]:
    return "mark_error" if state.get("error") else "save_version"


def route_after_evaluation_call(state: LessonState) -> Literal["save_evaluation", "mark_error"]:
    return "mark_error" if state.get("error") else "save_evaluation"


def route_after_evaluation(state: LessonState) -> Literal["approve_lesson", "generate_lesson", "reject_lesson"]:
    """The Decision Gate as a conditional edge. Python decides; the LLM never does."""
    decision = decide(state["overall_status"], state["attempt_number"], state["max_attempts"])
    logger.info("Decision gate", extra={"context": {
        "run_id": state["run_id"], "attempt": state["attempt_number"],
        "overall_status": state["overall_status"], "decision": decision}})
    return {"approve": "approve_lesson", "regenerate": "generate_lesson", "reject": "reject_lesson"}[decision]


def _criteria_for_storage(evaluation: dict[str, Any]) -> list[dict[str, Any]]:
    criteria = [dict(c) for c in evaluation["criteria"]]
    for criterion in criteria:
        if criterion["criterion"] == "topic_coverage":
            criterion["coverage"] = evaluation.get("coverage", [])
    return criteria


def build_lesson_graph(deps: LessonWorkflowDeps, checkpointer: Any = None) -> Any:

    def ids(state: LessonState) -> tuple[uuid.UUID, uuid.UUID]:
        return uuid.UUID(state["user_id"]), uuid.UUID(state["run_id"])

    def load_context(state: LessonState) -> LessonState:
        user_id, run_id = ids(state)
        with deps.session_scope() as db:
            run = lesson_service.get_lesson_run(db, user_id, run_id)
            profile = profile_service.get_learner_profile(db, user_id, run.chat_id)
            generator_prompt = db.get(PromptVersion, run.generator_prompt_version_id) \
                if run.generator_prompt_version_id else None
            evaluator_prompt = db.get(PromptVersion, run.evaluator_prompt_version_id) \
                if run.evaluator_prompt_version_id else None
            return {
                "chat_id": str(run.chat_id),
                "topic": run.topic,
                "topic_key": run.topic_key or "generic",
                "learner_profile": {name: getattr(profile, name, None) if profile else None
                                    for name in profile_service.PROFILE_FIELDS},
                "generator_instructions": generator_prompt.content if generator_prompt
                else DEFAULT_GENERATOR_INSTRUCTIONS,
                "evaluator_instructions": evaluator_prompt.content if evaluator_prompt
                else DEFAULT_EVALUATOR_INSTRUCTIONS,
                "max_attempts": run.max_attempts,
                "attempt_number": 0,
            }

    def generate_lesson(state: LessonState) -> LessonState:
        attempt = state.get("attempt_number", 0) + 1
        is_revision = attempt > 1
        feedback = state.get("evaluation_feedback") if is_revision else None
        request = GenerationRequest(
            topic=state["topic"], topic_config=get_topic(state["topic_key"]),
            learner_profile=state["learner_profile"], instructions=state["generator_instructions"],
            previous_lesson=state.get("lesson_markdown") if is_revision else None, feedback=feedback,
        )
        try:
            draft = deps.generator.generate(request)
        except LLMError as exc:
            return {"error": str(exc), "error_stage": "generation"}
        return {"attempt_number": attempt, "lesson_title": draft.title, "lesson_markdown": draft.lesson_markdown,
                "change_summary": draft.change_summary if is_revision else None,
                "generator_feedback": feedback, "error": None, "error_stage": None}

    def save_version(state: LessonState) -> LessonState:
        user_id, run_id = ids(state)
        with deps.session_scope() as db:
            version = lesson_service.add_lesson_version(
                db, user_id, run_id, content=state["lesson_markdown"],
                generator_feedback=state.get("generator_feedback"), change_summary=state.get("change_summary"),
                expected_attempt=state["attempt_number"],
            )
            return {"lesson_version_id": str(version.id)}

    def evaluate_lesson(state: LessonState) -> LessonState:
        request = EvaluationRequest(
            lesson_markdown=state["lesson_markdown"], topic=state["topic"],
            topic_config=get_topic(state["topic_key"]), learner_profile=state["learner_profile"],
            instructions=state["evaluator_instructions"],
        )
        try:
            report = deps.evaluator.evaluate(request)
        except LLMError as exc:
            return {"error": str(exc), "error_stage": "evaluation"}
        return {"overall_status": report.overall_status, "failed_criteria": list(report.failed_criteria),
                "evaluation": report.model_dump(mode="json"),
                "evaluation_feedback": report.feedback_for_generator, "error": None, "error_stage": None}

    def save_evaluation(state: LessonState) -> LessonState:
        user_id, _ = ids(state)
        with deps.session_scope() as db:
            lesson_service.add_evaluation(
                db, user_id, uuid.UUID(state["lesson_version_id"]),
                overall_status=state["overall_status"],
                criteria_results=_criteria_for_storage(state["evaluation"]),
                failed_criteria=state["failed_criteria"],
                feedback_for_generator=state.get("evaluation_feedback"),
            )
        return {}

    def _finish(state: LessonState, status: str, kind: str, message: str) -> LessonState:
        user_id, run_id = ids(state)
        with deps.session_scope() as db:
            run, changed = lesson_service.finish_lesson_run(db, user_id, run_id, status=status,
                                                            final_attempt_number=state["attempt_number"])
            if changed:
                chat = chat_service.get_chat(db, user_id, run.chat_id)
                chat.status = "completed"
                chat_service.add_message(db, user_id, run.chat_id, role="assistant", kind=kind, content=message,
                                         payload={"run_id": state["run_id"],
                                                  "attempt_number": state["attempt_number"]})
        return {}

    def approve_lesson(state: LessonState) -> LessonState:
        return _finish(state, "approved", "lesson_approved",
                       f"✅ Your lesson is ready: **{state['lesson_title']}**. It passed all six quality checks "
                       f"on attempt {state['attempt_number']} of {state['max_attempts']}.")

    def reject_lesson(state: LessonState) -> LessonState:
        return _finish(state, "rejected", "lesson_rejected",
                       f"I wrote {state['attempt_number']} versions of your lesson, but none passed all six quality "
                       "checks, so I won't show you an unapproved lesson. Open **Evaluation details** to see what "
                       "failed, or click **Try again** to start over.")

    def mark_error(state: LessonState) -> LessonState:
        user_id, run_id = ids(state)
        with deps.session_scope() as db:
            record_generation_failure(db, user_id, run_id, state.get("error") or "Unknown technical error.")
        return {}

    builder = StateGraph(LessonState)
    for name, node in (("load_context", load_context), ("generate_lesson", generate_lesson),
                       ("save_version", save_version), ("evaluate_lesson", evaluate_lesson),
                       ("save_evaluation", save_evaluation), ("approve_lesson", approve_lesson),
                       ("reject_lesson", reject_lesson), ("mark_error", mark_error)):
        builder.add_node(name, node)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "generate_lesson")
    builder.add_conditional_edges("generate_lesson", route_after_generation,
                                  {"save_version": "save_version", "mark_error": "mark_error"})
    builder.add_edge("save_version", "evaluate_lesson")
    builder.add_conditional_edges("evaluate_lesson", route_after_evaluation_call,
                                  {"save_evaluation": "save_evaluation", "mark_error": "mark_error"})
    builder.add_conditional_edges("save_evaluation", route_after_evaluation,
                                  {"approve_lesson": "approve_lesson", "generate_lesson": "generate_lesson",
                                   "reject_lesson": "reject_lesson"})
    builder.add_edge("approve_lesson", END)
    builder.add_edge("reject_lesson", END)
    builder.add_edge("mark_error", END)
    return builder.compile(checkpointer=checkpointer)
