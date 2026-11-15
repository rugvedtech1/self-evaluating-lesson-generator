"""Decision engine: Python rules over the AI's judgement (fake judge, no network)."""

import pytest
from pydantic import ValidationError

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.evaluator.criteria import CRITERION_KEYS
from app.evaluator.dataset import CASES, DATASET_PROFILE, GOOD_LESSON
from app.evaluator.engine import EvaluationRequest, LessonEvaluator
from app.evaluator.llm import LangChainLessonJudge
from app.evaluator.schemas import EvaluationReport, JudgedConcept, JudgedCriterion, LLMJudgement
from app.topics.intro_to_rag import INTRO_TO_RAG

QUOTE = "RAG stands for Retrieval-Augmented Generation"
POOR_FLOW = next(c for c in CASES if c.key == "poor_flow").lesson_markdown


def passing_judgement() -> LLMJudgement:
    return LLMJudgement(
        criteria=[JudgedCriterion(criterion=k, status="PASS", reason="Clearly meets this criterion.",
                                  evidence=[QUOTE]) for k in CRITERION_KEYS],
        coverage=[JudgedConcept(concept_key=c.key, status="PASS", evidence=QUOTE, reason="Explained.")
                  for c in INTRO_TO_RAG.required_concepts],
    )


def with_criterion(judgement: LLMJudgement, key: str, **changes) -> LLMJudgement:
    criteria = [c.model_copy(update=changes) if c.criterion == key else c for c in judgement.criteria]
    return judgement.model_copy(update={"criteria": criteria})


class FakeJudge:
    def __init__(self, judgement: LLMJudgement) -> None:
        self.judgement, self.requests = judgement, []

    def judge(self, request):
        self.requests.append(request)
        return self.judgement


def _evaluate(judgement: LLMJudgement, lesson: str = GOOD_LESSON) -> EvaluationReport:
    return LessonEvaluator(FakeJudge(judgement)).evaluate(EvaluationRequest(
        lesson_markdown=lesson, topic="Introduction to RAG", topic_config=INTRO_TO_RAG,
        learner_profile=DATASET_PROFILE))


def test_all_criteria_pass_means_overall_pass() -> None:
    report = _evaluate(passing_judgement())
    assert report.overall_status == "PASS"
    assert report.failed_criteria == []
    assert report.feedback_for_generator is None


def test_one_failed_criterion_means_overall_fail_with_feedback() -> None:
    judgement = with_criterion(passing_judgement(), "practical_examples", status="FAIL",
                               reason="The examples are not explained.",
                               improvement_instructions="Walk through the help-desk example step by step.")
    report = _evaluate(judgement)
    assert report.overall_status == "FAIL"
    assert report.failed_criteria == ["practical_examples"]
    assert "Walk through the help-desk example" in report.feedback_for_generator


def test_failed_concept_forces_topic_coverage_fail_even_if_ai_said_pass() -> None:
    judgement = passing_judgement()
    coverage = [c.model_copy(update={"status": "FAIL", "evidence": "MISSING", "reason": "Not explained."})
                if c.concept_key == "benefits_limitations" else c for c in judgement.coverage]
    report = _evaluate(judgement.model_copy(update={"coverage": coverage}))
    coverage_result = next(r for r in report.criteria if r.criterion == "topic_coverage")
    assert coverage_result.status == "FAIL"
    assert "Benefits and limitations of RAG" in coverage_result.improvement_instructions


def test_structural_failure_overrides_ai_pass() -> None:
    report = _evaluate(passing_judgement(), lesson=POOR_FLOW)
    flow = next(r for r in report.criteria if r.criterion == "teaching_flow")
    assert flow.status == "FAIL"
    assert "summary" in flow.improvement_instructions.lower()
    assert report.overall_status == "FAIL"


def test_pass_with_invented_evidence_is_an_invalid_response() -> None:
    judgement = with_criterion(passing_judgement(), "accuracy", evidence=["RAG retrains the model every time."])
    with pytest.raises(LLMResponseError, match="not found"):
        _evaluate(judgement)


def test_missing_concept_judgement_is_an_invalid_response() -> None:
    judgement = passing_judgement()
    with pytest.raises(LLMResponseError, match="every required concept"):
        _evaluate(judgement.model_copy(update={"coverage": judgement.coverage[:-1]}))


def test_unknown_concept_key_is_an_invalid_response() -> None:
    judgement = passing_judgement()
    coverage = [*judgement.coverage[:-1], judgement.coverage[-1].model_copy(update={"concept_key": "made_up"})]
    with pytest.raises(LLMResponseError):
        _evaluate(judgement.model_copy(update={"coverage": coverage}))


def test_report_cannot_claim_pass_with_a_failed_criterion() -> None:
    failing = _evaluate(with_criterion(passing_judgement(), "accuracy", status="FAIL",
                                       reason="Contains a false claim.", improvement_instructions="Remove it."))
    with pytest.raises(ValidationError):
        EvaluationReport.model_validate({**failing.model_dump(), "overall_status": "PASS"})


def test_judge_receives_structural_findings_and_topic_config() -> None:
    judge = FakeJudge(passing_judgement())
    LessonEvaluator(judge).evaluate(EvaluationRequest(
        lesson_markdown=POOR_FLOW, topic="Introduction to RAG", topic_config=INTRO_TO_RAG,
        learner_profile=DATASET_PROFILE))
    request = judge.requests[0]
    assert request.topic_config.key == "intro_to_rag"
    assert any(f.criterion == "teaching_flow" for f in request.structural_findings)


# ------------------------------------------------------------- LangChain judge boundary
class _Runnable:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error = result, error

    def invoke(self, _messages):
        if self.error is not None:
            raise self.error
        return self.result


class StubModel:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.kwargs = result, error, {}

    def with_structured_output(self, schema, **kwargs):
        self.kwargs = kwargs
        return _Runnable(self.result, self.error)


def _judge_request():
    from app.evaluator.schemas import JudgeRequest
    return JudgeRequest(lesson_markdown=GOOD_LESSON, topic="RAG", topic_config=INTRO_TO_RAG,
                        learner_profile={}, instructions="RUBRIC", structural_findings=[])


def test_judge_uses_function_calling_and_returns_validated_judgement() -> None:
    stub = StubModel(result=passing_judgement())
    assert LangChainLessonJudge(stub).judge(_judge_request()) == passing_judgement()
    assert stub.kwargs == {"method": "function_calling"}


def test_judge_invalid_output_is_response_error() -> None:
    with pytest.raises(LLMResponseError):
        LangChainLessonJudge(StubModel(result={"criteria": "not a list"})).judge(_judge_request())


def test_judge_provider_failure_is_unavailable() -> None:
    with pytest.raises(LLMUnavailableError):
        LangChainLessonJudge(StubModel(error=RuntimeError("timeout"))).judge(_judge_request())


class FlakyJudge:
    """Returns invalid output first, then a valid judgement."""

    def __init__(self, failures: int) -> None:
        self.failures, self.calls = failures, 0

    def judge(self, request):
        self.calls += 1
        if self.calls <= self.failures:
            raise LLMResponseError("invalid")
        return passing_judgement()


def _request() -> EvaluationRequest:
    return EvaluationRequest(lesson_markdown=GOOD_LESSON, topic="Introduction to RAG",
                             topic_config=INTRO_TO_RAG, learner_profile=DATASET_PROFILE)


def test_invalid_output_is_retried_once_then_succeeds() -> None:
    judge = FlakyJudge(failures=1)
    assert LessonEvaluator(judge, max_attempts=2).evaluate(_request()).overall_status == "PASS"
    assert judge.calls == 2


def test_retries_are_bounded() -> None:
    judge = FlakyJudge(failures=5)
    with pytest.raises(LLMResponseError):
        LessonEvaluator(judge, max_attempts=2).evaluate(_request())
    assert judge.calls == 2
