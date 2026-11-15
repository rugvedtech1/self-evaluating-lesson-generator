"""Pydantic validation of the AI judge's output: every malformed response is rejected."""

import pytest
from pydantic import ValidationError

from app.evaluator.criteria import CRITERIA, CRITERION_KEYS
from app.evaluator.schemas import LLMJudgement


def _criterion(key: str, status: str = "PASS", **overrides) -> dict:
    item = {"criterion": key, "status": status, "reason": "A clear reason for the verdict.",
            "evidence": ["RAG stands for Retrieval-Augmented Generation"],
            "improvement_instructions": None if status == "PASS" else "Add a concrete example."}
    item.update(overrides)
    return item


def _payload(criteria: list[dict] | None = None) -> dict:
    return {"criteria": criteria if criteria is not None else [_criterion(k) for k in CRITERION_KEYS],
            "coverage": [{"concept_key": "what_is_rag", "status": "PASS",
                          "evidence": "RAG stands for Retrieval-Augmented Generation", "reason": "Explained."}]}


def test_criteria_registry_matches_the_literal_type() -> None:
    assert tuple(spec.key for spec in CRITERIA) == CRITERION_KEYS
    assert len(CRITERION_KEYS) == 6


def test_valid_judgement_parses() -> None:
    assert len(LLMJudgement.model_validate(_payload()).criteria) == 6


def test_missing_criterion_is_rejected() -> None:
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload([_criterion(k) for k in CRITERION_KEYS[:5]]))


def test_duplicate_criterion_is_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS[:5]] + [_criterion(CRITERION_KEYS[0])]
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload(criteria))


def test_invalid_status_is_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[0]["status"] = "PARTIAL"
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload(criteria))


def test_missing_evidence_is_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[0]["evidence"] = []
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload(criteria))


def test_fail_without_improvement_instructions_is_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[0] = _criterion(CRITERION_KEYS[0], "FAIL", improvement_instructions=None)
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload(criteria))


def test_extra_evidence_quotes_are_trimmed_not_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[4]["evidence"] = [f"quote number {i} from the lesson" for i in range(8)]
    judgement = LLMJudgement.model_validate(_payload(criteria))
    assert len(judgement.criteria[4].evidence) == 5


def test_blank_evidence_items_do_not_count_as_evidence() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[0]["evidence"] = ["", "   "]
    with pytest.raises(ValidationError):
        LLMJudgement.model_validate(_payload(criteria))


def test_over_long_reason_is_trimmed_not_rejected() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[0]["reason"] = "x" * 5000
    assert len(LLMJudgement.model_validate(_payload(criteria)).criteria[0].reason) == 1500


def test_evidence_given_as_a_dictionary_is_converted_to_quotes() -> None:
    criteria = [_criterion(k) for k in CRITERION_KEYS]
    criteria[4]["evidence"] = {"what_is_rag": "RAG stands for Retrieval-Augmented Generation"}
    assert LLMJudgement.model_validate(_payload(criteria)).criteria[4].evidence == [
        "RAG stands for Retrieval-Augmented Generation"]


def test_concept_without_reason_is_accepted() -> None:
    payload = _payload()
    del payload["coverage"][0]["reason"]
    assert LLMJudgement.model_validate(payload).coverage[0].reason == ""


def test_criteria_and_coverage_given_as_dictionaries_are_converted() -> None:
    payload = _payload()
    payload["criteria"] = {c["criterion"]: {k: v for k, v in c.items() if k != "criterion"}
                           for c in payload["criteria"]}
    payload["coverage"] = {"what_is_rag": {"status": "PASS", "evidence": "RAG stands for Retrieval",
                                           "reason": "Explained."}}
    judgement = LLMJudgement.model_validate(payload)
    assert len(judgement.criteria) == 6 and judgement.coverage[0].concept_key == "what_is_rag"
