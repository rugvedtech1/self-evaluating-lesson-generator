"""Validation of a candidate generator prompt against a known set of learner profiles (before activation)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import BaseModel, Field

from app.core.exceptions import LLMError
from app.evaluator.engine import EvaluationRequest
from app.evaluator.schemas import EvaluationReport
from app.generator.schemas import GenerationRequest, LessonDraft
from app.topics.registry import match_topic


@dataclass(frozen=True)
class ValidationCase:
    key: str
    topic: str
    profile: dict[str, str]


VALIDATION_CASES: tuple[ValidationCase, ...] = (
    ValidationCase("rag_school_beginner", "Introduction to RAG", {
        "education_level": "12th standard", "english_proficiency": "Intermediate", "technical_background": "None",
        "ai_knowledge": "Has used ChatGPT a few times", "preferred_style": "Step-by-step"}),
    ValidationCase("rag_young_learner", "Introduction to RAG", {
        "education_level": "4th grade", "english_proficiency": "A little", "technical_background": "None",
        "ai_knowledge": "None", "preferred_style": "Short and direct"}),
)


class ValidationCaseResult(BaseModel):
    case: str
    overall_status: str | None
    failed_criteria: list[str] = Field(default_factory=list)
    error: str | None = None


class PromptValidationReport(BaseModel):
    passed: bool
    technical_error: bool
    cases: list[ValidationCaseResult]
    error: str | None = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GeneratorLike(Protocol):
    def generate(self, request: GenerationRequest) -> LessonDraft: ...


class EvaluatorLike(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport: ...


def validate_generator_prompt(prompt_text: str, generator: GeneratorLike, evaluator: EvaluatorLike,
                              cases: Sequence[ValidationCase] = VALIDATION_CASES) -> PromptValidationReport:
    """Strict: every case must PASS on a single attempt (no regeneration allowed during validation)."""
    results: list[ValidationCaseResult] = []
    for case in cases:
        topic_config = match_topic(case.topic)
        try:
            draft = generator.generate(GenerationRequest(topic=case.topic, topic_config=topic_config,
                                                         learner_profile=case.profile, instructions=prompt_text))
            report = evaluator.evaluate(EvaluationRequest(lesson_markdown=draft.lesson_markdown, topic=case.topic,
                                                          topic_config=topic_config, learner_profile=case.profile))
            results.append(ValidationCaseResult(case=case.key, overall_status=report.overall_status,
                                                failed_criteria=list(report.failed_criteria)))
        except LLMError as exc:
            results.append(ValidationCaseResult(case=case.key, overall_status=None, error=str(exc)))
    technical_error = any(r.error for r in results)
    passed = not technical_error and all(r.overall_status == "PASS" for r in results)
    return PromptValidationReport(passed=passed, technical_error=technical_error, cases=results)
