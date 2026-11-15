"""Evaluator data: what the AI judge must return (validated), and the final report Python builds.

Validation policy: strict about MEANING (all six criteria, PASS/FAIL only, evidence present,
FAIL => instructions), lenient about harmless FORMAT (extra quotes, over-long text are trimmed).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.evaluator.criteria import CRITERION_KEYS, CriterionKey
from app.topics.base import TopicConfig

Status = Literal["PASS", "FAIL"]
MAX_EVIDENCE_ITEMS = 5
MAX_TEXT = 1500
MAX_QUOTE = 600


def _trim(value: Any, limit: int) -> Any:
    return value.strip()[:limit] if isinstance(value, str) else value


class StructuralFinding(BaseModel):
    criterion: CriterionKey
    severity: Literal["fail", "warning"]
    message: str


# ------------------------------------------------------------------ AI judge output (validated)
class JudgedCriterion(BaseModel):
    criterion: CriterionKey
    status: Status
    reason: str = Field(min_length=10, description="Why this verdict, specific to this lesson.")
    evidence: list[str] = Field(
        min_length=1,
        description="1-3 SHORT EXACT quotes copied from the lesson (5-25 words each) supporting the verdict.",
    )
    improvement_instructions: str | None = Field(
        None, description="Required for FAIL: specific, actionable changes (what to add/change and where). "
                          "Null for PASS.",
    )

    @field_validator("evidence", mode="before")
    @classmethod
    def _normalise_evidence(cls, value: Any) -> Any:
        if isinstance(value, dict):      # {"concept": "quote", ...} -> ["quote", ...]
            value = list(value.values())
        elif isinstance(value, str):     # "quote" -> ["quote"]
            value = [value]
        if not isinstance(value, list):
            return value
        quotes = [_trim(str(item), MAX_QUOTE) for item in value if str(item).strip()]
        return quotes[:MAX_EVIDENCE_ITEMS]  # extra quotes are harmless: keep the first few

    @field_validator("reason", "improvement_instructions", mode="before")
    @classmethod
    def _trim_text(cls, value: Any) -> Any:
        return _trim(value, MAX_TEXT)

    @model_validator(mode="after")
    def _fail_needs_instructions(self) -> "JudgedCriterion":
        if self.status == "FAIL" and not (self.improvement_instructions or "").strip():
            raise ValueError("A FAIL verdict must include improvement_instructions.")
        return self


class JudgedConcept(BaseModel):
    concept_key: str = Field(description="Exact key of the required concept.")
    status: Status
    evidence: str = Field(min_length=1, description="EXACT quote from the lesson that explains it, or 'MISSING'.")
    reason: str = Field("", description="Short reason for the verdict.")

    @field_validator("evidence", mode="before")
    @classmethod
    def _evidence_text(cls, value: Any) -> Any:
        if isinstance(value, list):      # ["quote", ...] -> "quote"
            value = next((str(v) for v in value if str(v).strip()), "")
        return _trim(value, MAX_QUOTE)

    @field_validator("reason", mode="before")
    @classmethod
    def _reason_text(cls, value: Any) -> Any:
        return _trim(value, MAX_QUOTE) if value is not None else ""


class LLMJudgement(BaseModel):
    """Note: no overall verdict here on purpose. Python decides approval."""

    criteria: list[JudgedCriterion] = Field(min_length=6, max_length=6)
    coverage: list[JudgedConcept] = Field(min_length=1, description="One entry per required concept.")

    @field_validator("criteria", mode="before")
    @classmethod
    def _criteria_as_list(cls, value: Any) -> Any:
        if isinstance(value, dict):      # {"accuracy": {...}, ...} -> [{"criterion": "accuracy", ...}, ...]
            return [{"criterion": key, **item} if isinstance(item, dict) else item for key, item in value.items()]
        return value

    @field_validator("coverage", mode="before")
    @classmethod
    def _coverage_as_list(cls, value: Any) -> Any:
        if isinstance(value, dict):      # {"what_is_rag": {...}, ...} -> [{"concept_key": "what_is_rag", ...}, ...]
            return [{"concept_key": key, **item} if isinstance(item, dict) else item for key, item in value.items()]
        return value

    @model_validator(mode="after")
    def _each_criterion_exactly_once(self) -> "LLMJudgement":
        if sorted(c.criterion for c in self.criteria) != sorted(CRITERION_KEYS):
            raise ValueError("Each of the six criteria must be judged exactly once.")
        return self


@dataclass(frozen=True)
class JudgeRequest:
    lesson_markdown: str
    topic: str
    topic_config: TopicConfig
    learner_profile: Mapping[str, str | None]
    instructions: str
    structural_findings: Sequence[StructuralFinding]


# ------------------------------------------------------------------ final report (built by Python)
class CriterionResult(BaseModel):
    criterion: CriterionKey
    label: str
    status: Status
    reason: str
    evidence: list[str]
    improvement_instructions: str | None
    structural_findings: list[str] = Field(default_factory=list)


class ConceptResult(BaseModel):
    concept_key: str
    title: str
    status: Status
    evidence: str
    reason: str


class EvaluationReport(BaseModel):
    overall_status: Status
    criteria: list[CriterionResult]
    coverage: list[ConceptResult]
    failed_criteria: list[str]
    feedback_for_generator: str | None
    structural_findings: list[StructuralFinding]

    @model_validator(mode="after")
    def _no_partial_credit(self) -> "EvaluationReport":
        if sorted(c.criterion for c in self.criteria) != sorted(CRITERION_KEYS):
            raise ValueError("The report must contain each of the six criteria exactly once.")
        failed = [c.criterion for c in self.criteria if c.status == "FAIL"]
        if sorted(failed) != sorted(self.failed_criteria):
            raise ValueError("failed_criteria must list exactly the failed criteria.")
        if self.overall_status != ("FAIL" if failed else "PASS"):
            raise ValueError("overall_status may be PASS only when every criterion passes.")
        return self
