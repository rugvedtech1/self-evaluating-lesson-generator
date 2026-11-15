"""Lesson Evaluator: Python structural checks + AI judgement + Python validation and decision.

The AI judges meaning. Python enforces the rules: verified evidence, every concept judged,
coverage rule, structural failures, and the final PASS/FAIL (no partial credit).
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.exceptions import LLMResponseError
from app.evaluator.criteria import CRITERIA
from app.evaluator.evidence import normalise_text, quote_in_lesson
from app.evaluator.llm import LessonJudge
from app.evaluator.prompts import DEFAULT_EVALUATOR_INSTRUCTIONS
from app.evaluator.schemas import (
    ConceptResult, CriterionResult, EvaluationReport, JudgeRequest, LLMJudgement, StructuralFinding,
)
from app.evaluator.structural import run_structural_checks
from app.topics.base import TopicConfig


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvaluationRequest:
    lesson_markdown: str
    topic: str
    topic_config: TopicConfig
    learner_profile: Mapping[str, str | None]
    instructions: str = DEFAULT_EVALUATOR_INSTRUCTIONS  # Step 6: the active evaluator prompt version


def build_feedback(results: Sequence[CriterionResult]) -> str:
    lines = ["Fix ALL of the following problems found by the evaluator:"]
    lines += [f"- {r.label}: {r.reason} What to do: {r.improvement_instructions}"
              for r in results if r.status == "FAIL"]
    return "\n".join(lines)


def build_report(judgement: LLMJudgement, findings: Sequence[StructuralFinding],
                 lesson_markdown: str, topic_config: TopicConfig) -> EvaluationReport:
    lesson = normalise_text(lesson_markdown)

    # 1) every required concept judged exactly once, with real evidence for PASS
    expected = sorted(c.key for c in topic_config.required_concepts)
    if sorted(c.concept_key for c in judgement.coverage) != expected:
        raise LLMResponseError("The evaluator did not judge every required concept exactly once.")
    judged_concepts = {c.concept_key: c for c in judgement.coverage}
    coverage: list[ConceptResult] = []
    for concept in topic_config.required_concepts:
        item = judged_concepts[concept.key]
        if item.status == "PASS" and not quote_in_lesson(item.evidence, lesson):
            raise LLMResponseError(f"Evidence for concept '{concept.title}' was not found in the lesson: "
                                   f"{item.evidence[:200]!r}")
        reason = item.reason or ("Explained in the lesson." if item.status == "PASS" else "Not explained in the lesson.")
        coverage.append(ConceptResult(concept_key=concept.key, title=concept.title, status=item.status,
                                      evidence=item.evidence, reason=reason))
    missing = [c for c in coverage if c.status == "FAIL"]

    # 2) criteria: verified evidence + Python rules that override the AI
    verdicts = {v.criterion: v for v in judgement.criteria}
    results: list[CriterionResult] = []
    for spec in CRITERIA:
        verdict = verdicts[spec.key]
        verified = [q for q in verdict.evidence if quote_in_lesson(q, lesson)]
        if verdict.status == "PASS" and not verified:
            raise LLMResponseError(f"Evidence for '{spec.label}' was not found in the lesson: "
                                   f"{[q[:120] for q in verdict.evidence]!r}")

        status, reason = verdict.status, verdict.reason
        instructions = [verdict.improvement_instructions] if verdict.improvement_instructions else []
        notes = [f.message for f in findings if f.criterion == spec.key]
        hard = [f.message for f in findings if f.criterion == spec.key and f.severity == "fail"]

        if spec.key == "topic_coverage" and missing:
            if status == "PASS":
                reason = f"{len(missing)} required concept(s) are not explained (application rule)."
            status = "FAIL"
            instructions.append("Explain these required concepts: "
                                + "; ".join(f"{c.title} ({c.reason})" for c in missing))
        if hard:
            if status == "PASS":
                reason = "Automated structural check failed: " + " ".join(hard)
            status = "FAIL"
            instructions.append("Fix the structural problems: " + " ".join(hard))

        results.append(CriterionResult(
            criterion=spec.key, label=spec.label, status=status, reason=reason,
            evidence=verified or list(verdict.evidence),
            improvement_instructions=" ".join(instructions) if status == "FAIL" else None,
            structural_findings=notes,
        ))

    # 3) the decision: PASS only if all six PASS
    failed = [r.criterion for r in results if r.status == "FAIL"]
    return EvaluationReport(
        overall_status="FAIL" if failed else "PASS",
        criteria=results,
        coverage=coverage,
        failed_criteria=failed,
        feedback_for_generator=build_feedback(results) if failed else None,
        structural_findings=list(findings),
    )


class LessonEvaluator:
    """Bounded retry: an INVALID judge response is retried (max_attempts total); provider outages are not
    (the client already retried them). Either way, failure here is TECHNICAL, never a lesson verdict."""

    def __init__(self, judge: LessonJudge, max_attempts: int = 2) -> None:
        self._judge = judge
        self._max_attempts = max_attempts

    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        findings = run_structural_checks(request.lesson_markdown)
        judge_request = JudgeRequest(
            lesson_markdown=request.lesson_markdown, topic=request.topic, topic_config=request.topic_config,
            learner_profile=request.learner_profile, instructions=request.instructions,
            structural_findings=findings,
        )
        for attempt in range(1, self._max_attempts + 1):
            try:
                judgement = self._judge.judge(judge_request)
                return build_report(judgement, findings, request.lesson_markdown, request.topic_config)
            except LLMResponseError as exc:
                if attempt == self._max_attempts:
                    raise
                logger.warning("Invalid evaluation; retrying",
                               extra={"context": {"attempt": attempt, "error": str(exc)[:300]}})
        raise AssertionError("unreachable")
