"""One self-evolution cycle: aggregate → detect recurring patterns → candidate → validate → activate/reject."""

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evolution.patterns import (
    mark_patterns_addressed, recurring_patterns, reopen_patterns_addressed_by, sync_failure_patterns,
)
from app.evolution.playbook import build_candidate_prompt
from app.evolution.validation import PromptValidationReport
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.models import PromptVersion
from app.services.prompts import (
    activate_prompt, create_candidate_prompt, ensure_active_prompt, get_active_prompt, reject_prompt, rollback_prompt,
)

COMPONENT = "generator"
Validator = Callable[[str], PromptValidationReport]


class EvolutionOutcome(BaseModel):
    action: Literal["no_patterns", "no_new_rules", "activated", "rejected", "validation_error", "busy"]
    message: str
    candidate_version: int | None = None
    patterns: list[str] = Field(default_factory=list)
    added_rules: list[str] = Field(default_factory=list)


def run_evolution_cycle(session_scope: Callable[[], AbstractContextManager[Session]], validator: Validator,
                        min_occurrences: int = 3) -> EvolutionOutcome:
    # 1) analyse + create the candidate (short transaction)
    with session_scope() as db:
        busy = db.scalar(select(PromptVersion.id).where(PromptVersion.component == COMPONENT,
                                                        PromptVersion.status == "validating").limit(1))
        if busy is not None:
            return EvolutionOutcome(action="busy", message="Another candidate prompt is already being validated.")
        active = ensure_active_prompt(db, COMPONENT, DEFAULT_GENERATOR_INSTRUCTIONS)
        sync_failure_patterns(db, active.id)
        recurring = recurring_patterns(db, min_occurrences)
        names = [p.description for p in recurring]
        if not recurring:
            return EvolutionOutcome(action="no_patterns",
                                    message=f"No failure pattern has occurred {min_occurrences} or more times "
                                            f"under prompt v{active.version}.")
        content, added = build_candidate_prompt(active.content, recurring)
        if not added:
            return EvolutionOutcome(action="no_new_rules", patterns=names,
                                    message="The active prompt already has rules for every recurring pattern.")
        candidate = create_candidate_prompt(db, COMPONENT, content, parent=active,
                                            change_reason="Evolved for: " + "; ".join(names))
        candidate_id, version = candidate.id, candidate.version
        pattern_ids: list[uuid.UUID] = [p.id for p in recurring]

    # 2) validate (real LLM calls; NO database transaction open)
    try:
        report = validator(content)
    except Exception as exc:  # never leave a candidate stuck in "validating"
        report = PromptValidationReport(passed=False, technical_error=True, cases=[], error=str(exc)[:500])

    # 3) decide (short transaction)
    with session_scope() as db:
        candidate = db.get(PromptVersion, candidate_id)
        candidate.validation_report = report.model_dump(mode="json")
        common = {"candidate_version": version, "patterns": names, "added_rules": added}
        if report.technical_error:
            candidate.status = "draft"
            return EvolutionOutcome(action="validation_error", **common,
                                    message=f"v{version} could not be validated (technical error). "
                                            "The active prompt is unchanged.")
        if not report.passed:
            reject_prompt(db, candidate)
            return EvolutionOutcome(action="rejected", **common,
                                    message=f"v{version} failed validation and was rejected. "
                                            "The active prompt is unchanged.")
        activate_prompt(db, candidate)
        mark_patterns_addressed(db, pattern_ids, candidate.id)
        return EvolutionOutcome(action="activated", **common,
                                message=f"v{version} passed validation and is now the active generator prompt.")


def rollback_generator_prompt(db: Session, to_version: int | None = None) -> PromptVersion:
    current = get_active_prompt(db, COMPONENT)
    target = rollback_prompt(db, COMPONENT, to_version)
    if current is not None:
        reopen_patterns_addressed_by(db, current.id)  # its fixes are no longer active
    return target
