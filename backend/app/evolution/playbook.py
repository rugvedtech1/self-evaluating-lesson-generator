"""Turns recurring failure patterns into targeted, pre-written prompt rules (auditable; no LLM rewriting)."""

from collections.abc import Sequence
from typing import Protocol

from app.evolution.patterns import CONCEPT_TITLES

HEADER = "Lessons learned from recurring quality failures (added by prompt evolution):"

CRITERION_RULES = {
    "accuracy": "Accuracy check: re-read every factual claim before finishing. Remove anything you are not sure "
                "is true. Never state statistics, studies, dates or sources unless they are essential and well "
                "established.",
    "beginner_friendliness": "Beginner check: write for the learner's exact level. Use short sentences, everyday "
                             "words and one new idea per paragraph. For a young or very new learner, keep the lesson "
                             "shorter and simpler and leave out technical detail that is not needed.",
    "practical_examples": "Examples check: give every key concept a concrete, everyday example. After each "
                          "example, explain step by step how it works and which concept it illustrates.",
    "jargon_explanation": "Jargon check: the first time you use any technical term or abbreviation, expand it and "
                          "define it in one simple sentence. If a term is not needed, leave it out.",
    "topic_coverage": "Coverage check: give every required concept its own clearly headed section that explains "
                      "it, not just names it.",
    "teaching_flow": "Flow check: start with what the learner will learn and why it matters, explain basics before "
                     "advanced ideas, link each section to the next, and finish with a '## Summary' of key takeaways.",
}


class PatternLike(Protocol):
    criterion: str
    pattern_key: str


def rule_for(pattern: PatternLike) -> str | None:
    if pattern.pattern_key.startswith("topic_coverage:"):
        title = CONCEPT_TITLES.get(pattern.pattern_key.split(":", 1)[1])
        if title:
            return (f"Coverage check: the required concept '{title}' has often been missed. Give it its own "
                    "'## ' section that explains it clearly, not just names it.")
    return CRITERION_RULES.get(pattern.criterion)


def build_candidate_prompt(current: str, patterns: Sequence[PatternLike]) -> tuple[str, list[str]]:
    """Return (candidate prompt, rules added). Rules already present are never added twice."""
    new_rules: list[str] = []
    for pattern in patterns:
        rule = rule_for(pattern)
        if rule and rule not in current and rule not in new_rules:
            new_rules.append(rule)
    if not new_rules:
        return current, []
    body = current.rstrip()
    if HEADER not in body:
        body += "\n\n" + HEADER
    return body + "".join(f"\n- {rule}" for rule in new_rules), new_rules
