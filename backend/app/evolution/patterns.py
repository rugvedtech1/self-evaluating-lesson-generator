"""System-wide learning memory: recurring failure patterns.

Privacy by construction: rows hold only criterion keys, counts, timestamps and fixed wording from the
rubric/topic configuration. Never user ids, messages, profiles, lesson text or evaluator free text.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluator.criteria import CRITERIA_BY_KEY
from app.models import Evaluation, FailurePattern, LessonRun
from app.topics.base import GENERIC_TOPIC
from app.topics.registry import TOPICS

CONCEPT_TITLES = {c.key: c.title for topic in (*TOPICS, GENERIC_TOPIC) for c in topic.required_concepts}


@dataclass(frozen=True)
class PatternKey:
    criterion: str
    pattern_key: str
    description: str


def patterns_in_evaluation(failed_criteria: Iterable[str], criteria_results: Sequence[dict[str, Any]]) -> list[PatternKey]:
    """Map one FAIL evaluation to generic pattern keys (wording comes from our config, not the evaluator)."""
    found: list[PatternKey] = []
    for criterion in failed_criteria:
        spec = CRITERIA_BY_KEY.get(criterion)
        if spec is None:
            continue
        if criterion == "topic_coverage":
            missing = [c.get("concept_key") for r in criteria_results if r.get("criterion") == "topic_coverage"
                       for c in r.get("coverage", []) if c.get("status") == "FAIL"
                       and c.get("concept_key") in CONCEPT_TITLES]
            if missing:
                found += [PatternKey(criterion, f"{criterion}:{key}",
                                     f"Required concept not explained: {CONCEPT_TITLES[key]}")
                          for key in dict.fromkeys(missing)]
                continue
        found.append(PatternKey(criterion, criterion, f"{spec.label} failed"))
    return found


@dataclass
class _Tally:
    count: int = 0
    first: datetime | None = None
    last: datetime | None = None


def sync_failure_patterns(db: Session, prompt_version_id: uuid.UUID) -> list[FailurePattern]:
    """Recompute counts from the evaluations table (the source of truth) for runs using this prompt version."""
    rows = db.execute(
        select(Evaluation.failed_criteria, Evaluation.criteria_results, Evaluation.created_at)
        .join(LessonRun, LessonRun.id == Evaluation.run_id)
        .where(LessonRun.generator_prompt_version_id == prompt_version_id, Evaluation.overall_status == "FAIL")
    ).all()
    tallies: dict[PatternKey, _Tally] = {}
    for failed, results, created in rows:
        for key in patterns_in_evaluation(failed, results or []):
            tally = tallies.setdefault(key, _Tally())
            tally.count += 1
            tally.first = min(tally.first or created, created)
            tally.last = max(tally.last or created, created)

    existing = {(p.criterion, p.pattern_key): p for p in db.scalars(select(FailurePattern))}
    for key, tally in tallies.items():
        row = existing.get((key.criterion, key.pattern_key))
        if row is None:
            row = FailurePattern(criterion=key.criterion, pattern_key=key.pattern_key, description=key.description,
                                 occurrence_count=tally.count, first_seen_at=tally.first, last_seen_at=tally.last)
            db.add(row)
            existing[(key.criterion, key.pattern_key)] = row
        else:
            row.occurrence_count = tally.count
            row.last_seen_at = tally.last
    seen = {(k.criterion, k.pattern_key) for k in tallies}
    for identity, row in existing.items():
        if identity not in seen:
            row.occurrence_count = 0  # nothing recorded under the current prompt
    db.flush()
    return sorted(existing.values(), key=lambda p: (-p.occurrence_count, p.pattern_key))


def recurring_patterns(db: Session, min_occurrences: int) -> list[FailurePattern]:
    return list(db.scalars(select(FailurePattern).where(
        FailurePattern.status == "open", FailurePattern.occurrence_count >= min_occurrences)
        .order_by(FailurePattern.occurrence_count.desc(), FailurePattern.pattern_key)))


def mark_patterns_addressed(db: Session, pattern_ids: Sequence[uuid.UUID], prompt_id: uuid.UUID) -> None:
    for pattern in db.scalars(select(FailurePattern).where(FailurePattern.id.in_(pattern_ids))):
        pattern.status = "addressed"
        pattern.resolved_by_prompt_id = prompt_id
    db.flush()


def reopen_patterns_addressed_by(db: Session, prompt_id: uuid.UUID) -> None:
    for pattern in db.scalars(select(FailurePattern).where(FailurePattern.resolved_by_prompt_id == prompt_id)):
        pattern.status = "open"
        pattern.resolved_by_prompt_id = None
    db.flush()
