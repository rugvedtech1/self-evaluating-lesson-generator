"""Candidate prompt validation: every validation lesson must PASS on a single attempt."""

from app.core.exceptions import LLMUnavailableError
from app.evaluator.criteria import CRITERIA_BY_KEY, CRITERION_KEYS
from app.evaluator.schemas import CriterionResult, EvaluationReport
from app.evolution.validation import VALIDATION_CASES, validate_generator_prompt
from app.generator.schemas import LessonDraft


def report(*failed: str) -> EvaluationReport:
    criteria = [CriterionResult(criterion=k, label=CRITERIA_BY_KEY[k].label, status="FAIL" if k in failed else "PASS",
                                reason="r", evidence=["q"], improvement_instructions="fix" if k in failed else None)
                for k in CRITERION_KEYS]
    return EvaluationReport(overall_status="FAIL" if failed else "PASS", criteria=criteria, coverage=[],
                            failed_criteria=list(failed), feedback_for_generator=None, structural_findings=[])


class Generator:
    def __init__(self, error=None) -> None:
        self.error, self.prompts = error, []

    def generate(self, request):
        self.prompts.append(request.instructions)
        if self.error:
            raise self.error
        return LessonDraft(title="RAG", lesson_markdown="# RAG\n\n" + "Simple words. " * 30)


class Evaluator:
    def __init__(self, *reports) -> None:
        self.reports = list(reports)

    def evaluate(self, request):
        return self.reports.pop(0)


def test_all_cases_passing_means_validated_and_candidate_text_is_used() -> None:
    generator = Generator()
    result = validate_generator_prompt("CANDIDATE", generator, Evaluator(*[report() for _ in VALIDATION_CASES]))
    assert result.passed and not result.technical_error
    assert set(generator.prompts) == {"CANDIDATE"}


def test_one_failing_case_fails_validation() -> None:
    result = validate_generator_prompt("CANDIDATE", Generator(), Evaluator(report(), report("beginner_friendliness")))
    assert not result.passed and not result.technical_error
    assert result.cases[1].failed_criteria == ["beginner_friendliness"]


def test_api_failure_is_a_technical_error_not_a_quality_verdict() -> None:
    result = validate_generator_prompt("CANDIDATE", Generator(error=LLMUnavailableError("down")), Evaluator())
    assert result.technical_error and not result.passed
