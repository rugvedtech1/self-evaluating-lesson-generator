"""System-wide failure patterns: extraction, counting per prompt window, privacy."""

from contextlib import contextmanager

import pytest
from sqlalchemy import inspect

from app.evolution.patterns import patterns_in_evaluation, recurring_patterns, sync_failure_patterns
from app.models import FailurePattern
from app.services import chats as chat_svc
from app.services import lessons as lesson_svc
from app.services.prompts import ensure_active_prompt

PRIVATE_DETAIL = "Too hard for Asha, a 4th grade learner from Pune"


def record_failure(db, user, prompt_id, failed=("jargon_explanation",), missing=()):
    chat = chat_svc.create_chat(db, user)
    run = lesson_svc.create_lesson_run(db, user, chat.id, topic="Introduction to RAG", topic_key="intro_to_rag",
                                       generator_prompt_version_id=prompt_id)
    version = lesson_svc.add_lesson_version(db, user, run.id, content=f"# Lesson\n\n{PRIVATE_DETAIL}")
    results = [{"criterion": c, "status": "FAIL", "reason": PRIVATE_DETAIL} for c in failed]
    if missing:
        results.append({"criterion": "topic_coverage", "status": "FAIL", "reason": PRIVATE_DETAIL,
                        "coverage": [{"concept_key": k, "title": "x", "status": "FAIL"} for k in missing]})
        failed = (*failed, "topic_coverage")
    lesson_svc.add_evaluation(db, user, version.id, overall_status="FAIL", criteria_results=results,
                              failed_criteria=list(failed), feedback_for_generator=PRIVATE_DETAIL)


def test_evaluation_maps_to_generic_patterns() -> None:
    results = [{"criterion": "topic_coverage", "coverage": [
        {"concept_key": "benefits_limitations", "status": "FAIL"}, {"concept_key": "what_is_rag", "status": "PASS"}]}]
    keys = patterns_in_evaluation(["jargon_explanation", "topic_coverage"], results)
    assert [k.pattern_key for k in keys] == ["jargon_explanation", "topic_coverage:benefits_limitations"]
    assert keys[1].description == "Required concept not explained: Benefits and limitations of RAG"


def test_unknown_criteria_and_concepts_are_ignored() -> None:
    results = [{"criterion": "topic_coverage", "coverage": [{"concept_key": "made_up", "status": "FAIL"}]}]
    keys = patterns_in_evaluation(["not_a_criterion", "topic_coverage"], results)
    assert [k.pattern_key for k in keys] == ["topic_coverage"]


@pytest.mark.db
def test_counts_only_failures_under_the_active_prompt(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    active = ensure_active_prompt(db_session, "generator", "BASE PROMPT")
    record_failure(db_session, alice, active.id)
    record_failure(db_session, bob, active.id)
    record_failure(db_session, bob, None)  # a run under some other prompt does not count
    patterns = {p.pattern_key: p.occurrence_count for p in sync_failure_patterns(db_session, active.id)}
    assert patterns == {"jargon_explanation": 2}


@pytest.mark.db
def test_learning_memory_holds_no_user_data(db_session, make_user) -> None:
    active = ensure_active_prompt(db_session, "generator", "BASE PROMPT")
    record_failure(db_session, make_user(), active.id, missing=("benefits_limitations",))
    columns = {c["name"] for c in inspect(db_session.get_bind()).get_columns("failure_patterns")}
    assert not {"user_id", "chat_id", "run_id", "content", "reason"} & columns
    for pattern in sync_failure_patterns(db_session, active.id):
        assert "Asha" not in pattern.description and "Pune" not in pattern.description


@pytest.mark.db
def test_recurring_requires_threshold_and_open_status(db_session, make_user) -> None:
    active = ensure_active_prompt(db_session, "generator", "BASE PROMPT")
    user = make_user()
    for _ in range(3):
        record_failure(db_session, user, active.id, failed=("jargon_explanation",))
    record_failure(db_session, user, active.id, failed=("accuracy",))
    sync_failure_patterns(db_session, active.id)
    assert [p.pattern_key for p in recurring_patterns(db_session, 3)] == ["jargon_explanation"]
    db_session.query(FailurePattern).update({"status": "dismissed"})
    assert recurring_patterns(db_session, 3) == []
