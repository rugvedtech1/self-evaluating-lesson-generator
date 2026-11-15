"""Full self-evolution cycle with a fake validator (no LLM)."""

from contextlib import contextmanager

import pytest

from app.evolution.cycle import rollback_generator_prompt, run_evolution_cycle
from app.evolution.playbook import CRITERION_RULES
from app.evolution.validation import PromptValidationReport, ValidationCaseResult
from app.models import FailurePattern
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.services.prompts import create_candidate_prompt, ensure_active_prompt, get_active_prompt
from app.workflows.runner import start_lesson_run

pytestmark = pytest.mark.db


def _scope(db_session):
    @contextmanager
    def scope():
        with db_session.begin_nested():
            yield db_session
    return scope


def _fail(db, user, prompt_id, criterion="jargon_explanation"):
    chat = chat_svc.create_chat(db, user)
    run = lesson_svc.create_lesson_run(db, user, chat.id, topic="RAG", generator_prompt_version_id=prompt_id)
    version = lesson_svc.add_lesson_version(db, user, run.id, content="# L\n\nx")
    lesson_svc.add_evaluation(db, user, version.id, overall_status="FAIL",
                              criteria_results=[{"criterion": criterion, "status": "FAIL"}],
                              failed_criteria=[criterion])


def _report(passed=True, technical=False) -> PromptValidationReport:
    case = ValidationCaseResult(case="c", overall_status=None if technical else ("PASS" if passed else "FAIL"),
                                error="down" if technical else None)
    return PromptValidationReport(passed=passed and not technical, technical_error=technical, cases=[case])


class Validator:
    def __init__(self, report) -> None:
        self.report, self.prompts = report, []

    def __call__(self, text):
        self.prompts.append(text)
        return self.report


@pytest.fixture
def recurring(db_session, make_user):
    v1 = ensure_active_prompt(db_session, "generator", "BASE PROMPT")
    user = make_user()
    for _ in range(3):
        _fail(db_session, user, v1.id)
    return v1


def test_no_recurring_failures_means_no_candidate(db_session) -> None:
    ensure_active_prompt(db_session, "generator", "BASE PROMPT")
    validator = Validator(_report())
    outcome = run_evolution_cycle(_scope(db_session), validator, min_occurrences=3)
    assert outcome.action == "no_patterns" and validator.prompts == []


def test_recurring_pattern_produces_validated_and_activated_prompt(db_session, recurring) -> None:
    validator = Validator(_report())
    outcome = run_evolution_cycle(_scope(db_session), validator, min_occurrences=3)
    assert outcome.action == "activated" and outcome.candidate_version == 2
    active = get_active_prompt(db_session, "generator")
    assert active.version == 2 and CRITERION_RULES["jargon_explanation"] in active.content
    assert active.validation_report["passed"] is True
    assert validator.prompts == [active.content]  # exactly the activated text was validated
    pattern = db_session.query(FailurePattern).filter_by(pattern_key="jargon_explanation").one()
    assert (pattern.status, pattern.resolved_by_prompt_id) == ("addressed", active.id)


def test_failed_validation_rejects_candidate_and_keeps_active_prompt(db_session, recurring) -> None:
    outcome = run_evolution_cycle(_scope(db_session), Validator(_report(passed=False)), min_occurrences=3)
    assert outcome.action == "rejected"
    assert get_active_prompt(db_session, "generator").id == recurring.id
    assert db_session.query(FailurePattern).filter_by(pattern_key="jargon_explanation").one().status == "open"


def test_validation_api_error_changes_nothing(db_session, recurring) -> None:
    outcome = run_evolution_cycle(_scope(db_session), Validator(_report(technical=True)), min_occurrences=3)
    assert outcome.action == "validation_error"
    assert get_active_prompt(db_session, "generator").id == recurring.id


def test_crashing_validator_never_leaves_a_candidate_stuck(db_session, recurring) -> None:
    def broken(_text):
        raise RuntimeError("boom")
    assert run_evolution_cycle(_scope(db_session), broken, min_occurrences=3).action == "validation_error"
    assert run_evolution_cycle(_scope(db_session), Validator(_report()), min_occurrences=3).action == "activated"


def test_no_duplicate_rules_when_pattern_recurs_after_fix(db_session, recurring, make_user) -> None:
    run_evolution_cycle(_scope(db_session), Validator(_report()), min_occurrences=3)
    v2 = get_active_prompt(db_session, "generator")
    user = make_user()
    for _ in range(3):
        _fail(db_session, user, v2.id)
    db_session.query(FailurePattern).update({"status": "open"})
    outcome = run_evolution_cycle(_scope(db_session), Validator(_report()), min_occurrences=3)
    assert outcome.action == "no_new_rules"


def test_cycle_refuses_while_another_candidate_is_validating(db_session, recurring) -> None:
    create_candidate_prompt(db_session, "generator", "x", parent=recurring, change_reason="in progress")
    assert run_evolution_cycle(_scope(db_session), Validator(_report()), min_occurrences=3).action == "busy"


def test_rollback_reopens_patterns_and_new_runs_use_the_active_prompt(db_session, recurring, make_user) -> None:
    run_evolution_cycle(_scope(db_session), Validator(_report()), min_occurrences=3)
    v2 = get_active_prompt(db_session, "generator")

    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id, {"topic": "Introduction to RAG"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    assert start_lesson_run(db_session, user, chat.id).generator_prompt_version_id == v2.id

    assert rollback_generator_prompt(db_session).id == recurring.id
    assert db_session.query(FailurePattern).filter_by(pattern_key="jargon_explanation").one().status == "open"
