"""Full quality-control loop: generate → evaluate → Decision Gate → regenerate | approve | reject (fakes)."""

from contextlib import contextmanager
from dataclasses import dataclass, field

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.evaluator.criteria import CRITERIA_BY_KEY, CRITERION_KEYS
from app.evaluator.schemas import CriterionResult, EvaluationReport
from app.generator.schemas import LessonDraft
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc
from app.services import lessons as lesson_svc
from app.workflows.lesson_graph import (
    LessonWorkflowDeps, build_lesson_graph, route_after_evaluation, route_after_generation,
)
from app.workflows.runner import LessonWorkflowRunner, start_lesson_run

pytestmark = pytest.mark.db
BODY = "Short, simple sentences explain each idea. " * 10


def report(*failed: str) -> EvaluationReport:
    criteria = [CriterionResult(criterion=k, label=CRITERIA_BY_KEY[k].label,
                                status="FAIL" if k in failed else "PASS", reason="Judged by the fake evaluator.",
                                evidence=["quote"], improvement_instructions=f"Fix {k}." if k in failed else None)
                for k in CRITERION_KEYS]
    return EvaluationReport(overall_status="FAIL" if failed else "PASS", criteria=criteria, coverage=[],
                            failed_criteria=list(failed), structural_findings=[],
                            feedback_for_generator=("Fix these: " + ", ".join(failed)) if failed else None)


@dataclass
class FakeGenerator:
    error_on_call: dict[int, Exception] = field(default_factory=dict)
    requests: list = field(default_factory=list)

    def generate(self, request):
        self.requests.append(request)
        n = len(self.requests)
        if n in self.error_on_call:
            raise self.error_on_call[n]
        return LessonDraft(title=f"RAG lesson v{n}", lesson_markdown=f"# RAG lesson v{n}\n\n{BODY}",
                           change_summary=f"Changes in v{n}" if n > 1 else None)


@dataclass
class FakeEvaluator:
    outcomes: list = field(default_factory=list)  # EvaluationReport or Exception, consumed in order
    requests: list = field(default_factory=list)

    def evaluate(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _scope(db_session):
    @contextmanager
    def scope():
        with db_session.begin_nested():
            yield db_session
    return scope


def _graph(db_session, generator, evaluator, saver=None):
    deps = LessonWorkflowDeps(session_scope=_scope(db_session), generator=generator, evaluator=evaluator)
    return build_lesson_graph(deps, checkpointer=saver or InMemorySaver())


def _config(run) -> dict:
    return {"configurable": {"thread_id": str(run.id)}}


def _invoke(graph, user, run) -> dict:
    return graph.invoke({"run_id": str(run.id), "user_id": str(user)}, _config(run))


def _history(db_session, user, run):
    db_session.expire_all()
    return lesson_svc.get_lesson_run_history(db_session, user, run.id)


@pytest.fixture
def started(db_session, make_user):
    user = make_user()
    chat = chat_svc.create_chat(db_session, user)
    profile_svc.upsert_learner_profile(db_session, user, chat.id, {"topic": "Introduction to RAG"})
    profile_svc.confirm_learner_profile(db_session, user, chat.id)
    chat.status = "generating"
    return user, chat, start_lesson_run(db_session, user, chat.id)


def test_first_attempt_approval(db_session, started) -> None:
    user, chat, run = started
    _invoke(_graph(db_session, FakeGenerator(), FakeEvaluator([report()])), user, run)
    history = _history(db_session, user, run)
    assert (history.run.status, history.run.final_attempt_number) == ("approved", 1)
    assert [a.evaluation.overall_status for a in history.attempts] == ["PASS"]
    assert chat_svc.get_chat(db_session, user, chat.id).status == "completed"
    assert chat_svc.list_messages(db_session, user, chat.id)[-1].kind == "lesson_approved"


def test_second_attempt_approval_uses_evaluator_feedback(db_session, started) -> None:
    user, _, run = started
    generator = FakeGenerator()
    _invoke(_graph(db_session, generator, FakeEvaluator([report("jargon_explanation"), report()])), user, run)

    second = generator.requests[1]
    assert second.previous_lesson.startswith("# RAG lesson v1")
    assert "jargon_explanation" in second.feedback
    history = _history(db_session, user, run)
    assert (history.run.status, history.run.final_attempt_number) == ("approved", 2)
    v2 = history.attempts[1].version
    assert v2.generator_feedback == second.feedback
    assert v2.change_summary == "Changes in v2"
    assert history.attempts[0].evaluation.failed_criteria == ["jargon_explanation"]


def test_third_attempt_approval(db_session, started) -> None:
    user, _, run = started
    evaluator = FakeEvaluator([report("accuracy"), report("teaching_flow"), report()])
    _invoke(_graph(db_session, FakeGenerator(), evaluator), user, run)
    history = _history(db_session, user, run)
    assert (history.run.status, history.run.final_attempt_number) == ("approved", 3)
    assert [a.evaluation.overall_status for a in history.attempts] == ["FAIL", "FAIL", "PASS"]


def test_three_failures_mean_rejection_and_no_fourth_attempt(db_session, started) -> None:
    user, chat, run = started
    generator = FakeGenerator()
    evaluator = FakeEvaluator([report("accuracy"), report("accuracy"), report("accuracy")])
    _invoke(_graph(db_session, generator, evaluator), user, run)
    history = _history(db_session, user, run)
    assert history.run.status == "rejected"
    assert len(generator.requests) == 3
    assert [a.evaluation.overall_status for a in history.attempts] == ["FAIL", "FAIL", "FAIL"]
    assert chat_svc.list_messages(db_session, user, chat.id)[-1].kind == "lesson_rejected"


def test_retry_limit_comes_from_the_run_not_the_llm(db_session, started) -> None:
    user, _, run = started
    run.max_attempts = 2
    db_session.flush()
    generator = FakeGenerator()
    _invoke(_graph(db_session, generator, FakeEvaluator([report("accuracy"), report("accuracy")])), user, run)
    assert len(generator.requests) == 2
    assert _history(db_session, user, run).run.status == "rejected"


def test_generation_api_failure_is_technical_error_not_rejection(db_session, started) -> None:
    user, chat, run = started
    generator = FakeGenerator(error_on_call={2: LLMUnavailableError("down")})
    state = _invoke(_graph(db_session, generator, FakeEvaluator([report("accuracy")])), user, run)
    assert state["error_stage"] == "generation"
    history = _history(db_session, user, run)
    assert history.run.status == "error"
    assert len(history.attempts) == 1 and history.attempts[0].evaluation.overall_status == "FAIL"
    assert chat_svc.get_chat(db_session, user, chat.id).status == "failed"


def test_evaluator_api_failure_is_technical_error(db_session, started) -> None:
    user, _, run = started
    state = _invoke(_graph(db_session, FakeGenerator(), FakeEvaluator([LLMUnavailableError("down")])), user, run)
    assert state["error_stage"] == "evaluation"
    history = _history(db_session, user, run)
    assert history.run.status == "error"
    assert len(history.attempts) == 1 and history.attempts[0].evaluation is None


def test_invalid_evaluator_response_is_technical_error_not_rejection(db_session, started) -> None:
    user, _, run = started
    _invoke(_graph(db_session, FakeGenerator(), FakeEvaluator([LLMResponseError("invalid")])), user, run)
    assert _history(db_session, user, run).run.status == "error"


def test_state_is_checkpointed_per_run(db_session, started) -> None:
    user, _, run = started
    graph = _graph(db_session, FakeGenerator(), FakeEvaluator([report()]), InMemorySaver())
    _invoke(graph, user, run)
    snapshot = graph.get_state(_config(run))
    assert snapshot.values["overall_status"] == "PASS"
    assert snapshot.next == ()


def test_crash_mid_run_is_resumed_from_checkpoint_without_regenerating(db_session, started) -> None:
    user, _, run = started
    generator = FakeGenerator()
    evaluator = FakeEvaluator([RuntimeError("server died"), report()])
    graph = _graph(db_session, generator, evaluator, InMemorySaver())
    with pytest.raises(RuntimeError):
        _invoke(graph, user, run)
    assert graph.get_state(_config(run)).next == ("evaluate_lesson",)

    LessonWorkflowRunner(graph, session_scope=_scope(db_session)).resume(run.id, user)
    history = _history(db_session, user, run)
    assert history.run.status == "approved"
    assert len(generator.requests) == 1  # resumed at evaluation: version 1 was not written again
    assert len(history.attempts) == 1


def test_runner_records_unexpected_crash_as_technical_failure(db_session, started) -> None:
    user, chat, run = started

    class ExplodingGraph:
        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("bug")

    LessonWorkflowRunner(ExplodingGraph(), session_scope=_scope(db_session)).run(run.id, user)
    db_session.expire_all()
    assert lesson_svc.get_lesson_run(db_session, user, run.id).status == "error"
    assert chat_svc.get_chat(db_session, user, chat.id).status == "failed"


def test_routing_after_generation() -> None:
    assert route_after_generation({"error": "API down"}) == "mark_error"
    assert route_after_generation({"error": None}) == "save_version"


def test_routing_after_evaluation_follows_the_decision_gate() -> None:
    def state(status: str, attempt: int) -> dict:
        return {"run_id": "r", "overall_status": status, "attempt_number": attempt, "max_attempts": 3}
    assert route_after_evaluation(state("PASS", 1)) == "approve_lesson"
    assert route_after_evaluation(state("FAIL", 1)) == "generate_lesson"
    assert route_after_evaluation(state("FAIL", 3)) == "reject_lesson"
