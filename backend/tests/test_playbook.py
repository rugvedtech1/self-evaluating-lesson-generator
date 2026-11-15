"""Playbook: recurring patterns become specific, non-duplicated prompt rules."""

from types import SimpleNamespace

from app.evolution.playbook import CRITERION_RULES, HEADER, build_candidate_prompt


def _p(criterion: str, key: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(criterion=criterion, pattern_key=key or criterion)


def test_adds_one_rule_per_recurring_criterion() -> None:
    content, added = build_candidate_prompt("BASE", [_p("jargon_explanation"), _p("accuracy")])
    assert added == [CRITERION_RULES["jargon_explanation"], CRITERION_RULES["accuracy"]]
    assert content.startswith("BASE") and content.count(HEADER) == 1


def test_missing_concept_gets_a_concept_specific_rule() -> None:
    _, added = build_candidate_prompt("BASE", [_p("topic_coverage", "topic_coverage:benefits_limitations")])
    assert "Benefits and limitations of RAG" in added[0]


def test_rules_already_present_are_not_added_again() -> None:
    first, _ = build_candidate_prompt("BASE", [_p("jargon_explanation")])
    second, added = build_candidate_prompt(first, [_p("jargon_explanation")])
    assert added == [] and second == first


def test_existing_header_is_reused_for_new_rules() -> None:
    first, _ = build_candidate_prompt("BASE", [_p("jargon_explanation")])
    second, added = build_candidate_prompt(first, [_p("accuracy")])
    assert added and second.count(HEADER) == 1
