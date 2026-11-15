"""OPTIONAL end-to-end run with the REAL Generator and Evaluator (about $0.01-0.03). Skipped by default.

Run with:  RUN_LIVE_LLM_TESTS=1 pytest backend/tests/test_workflow_live.py -v -s
"""

import os
from contextlib import contextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import get_settings
from app.evaluator.engine import LessonEvaluator
from app.evaluator.llm import LangChainLessonJudge
from app.generator.llm import LangChainLessonGenerator
from app.llm.factory import build_chat_model
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.workflows.lesson_graph import LessonWorkflowDeps, build_lesson_graph
from app.workflows.runner import start_lesson_run

pytestmark = [pytest.mark.live, pytest.mark.db]


def test_real_generate_evaluate_loop(db_session, make_user) -> None:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to call the real LLM (costs a small amount).")

    @contextmanager
    def scope():
        with db_session.begin_nested():
            yield db_session

    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id, {
        "topic": "Introduction to RAG", "education_level": "12th standard", "english_proficiency": "Beginner",
        "technical_background": "None", "ai_knowledge": "Never used AI tools", "preferred_style": "Step-by-step"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    run = start_lesson_run(db_session, user, chat.id)

    settings = get_settings()
    deps = LessonWorkflowDeps(
        session_scope=scope,
        generator=LangChainLessonGenerator(build_chat_model("generator", temperature=0.4,
                                                            max_tokens=settings.generator_max_tokens)),
        evaluator=LessonEvaluator(LangChainLessonJudge(build_chat_model("evaluator", temperature=0,
                                                                        max_tokens=settings.evaluator_max_tokens))),
    )
    build_lesson_graph(deps, checkpointer=InMemorySaver()).invoke(
        {"run_id": str(run.id), "user_id": str(user)}, {"configurable": {"thread_id": str(run.id)}})

    db_session.expire_all()
    history = lesson_svc.get_lesson_run_history(db_session, user, run.id)
    for a in history.attempts:
        ev = a.evaluation
        print(f"\nattempt {a.version.attempt_number}: {ev.overall_status if ev else 'not evaluated'} "
              f"failed={ev.failed_criteria if ev else '-'}")
    print(f"FINAL: {history.run.status} (attempt {history.run.final_attempt_number})")
    assert history.run.status in ("approved", "rejected")
    assert all(a.evaluation is not None for a in history.attempts)
