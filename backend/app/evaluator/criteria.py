"""The six mandatory rubric criteria (general; topic-specific concepts live in app/topics)."""

from dataclasses import dataclass
from typing import Literal, get_args

CriterionKey = Literal[
    "accuracy", "beginner_friendliness", "practical_examples",
    "jargon_explanation", "topic_coverage", "teaching_flow",
]
CRITERION_KEYS: tuple[str, ...] = get_args(CriterionKey)


@dataclass(frozen=True)
class CriterionSpec:
    key: str
    label: str
    checks: tuple[str, ...]


CRITERIA: tuple[CriterionSpec, ...] = (
    CriterionSpec("accuracy", "Accuracy and grounding", (
        "technically correct", "no misleading statements", "internally consistent",
        "no fabricated statistics, studies or sources presented as facts")),
    CriterionSpec("beginner_friendliness", "Beginner friendliness", (
        "understandable for someone starting from zero", "simple English",
        "difficult ideas explained in smaller steps", "no assumed advanced knowledge")),
    CriterionSpec("practical_examples", "Practical examples", (
        "meaningful real-world examples", "examples related to the topic",
        "explains how the examples work", "connects examples to the technical concepts")),
    CriterionSpec("jargon_explanation", "Jargon explanation", (
        "technical terms are explained", "abbreviations are expanded",
        "terminology introduced in a logical order", "explanations are beginner-friendly")),
    CriterionSpec("topic_coverage", "Topic coverage", (
        "every required concept is actually explained; merely naming it is not enough",)),
    CriterionSpec("teaching_flow", "Teaching flow", (
        "logical order", "clear introduction", "basic concepts before advanced ones",
        "connected sections", "useful summary")),
)
CRITERIA_BY_KEY = {spec.key: spec for spec in CRITERIA}
