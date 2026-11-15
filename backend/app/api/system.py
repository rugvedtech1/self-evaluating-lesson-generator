"""System learning: failure patterns + prompt versions (read: any user; change: admins only)."""

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, status

from app.api.deps import AdminUser, CurrentUser, DbSession, EvolutionServiceDep
from app.core.config import get_settings
from app.evolution.cycle import rollback_generator_prompt
from app.evolution.patterns import sync_failure_patterns
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.models import FailurePattern, PromptVersion
from app.schemas.system import EvolutionStarted, FailurePatternOut, PromptVersionOut, RollbackRequest
from app.services.prompts import ensure_active_prompt, list_prompt_versions

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/prompts/{component}", response_model=list[PromptVersionOut])
def list_prompts(component: Literal["intake", "generator", "evaluator"], user: CurrentUser,
                 db: DbSession) -> list[PromptVersion]:
    return list_prompt_versions(db, component)


@router.get("/failure-patterns", response_model=list[FailurePatternOut])
def failure_patterns(user: CurrentUser, db: DbSession) -> list[FailurePattern]:
    """Recomputed from evaluations for the active generator prompt. Anonymous counts only."""
    active = ensure_active_prompt(db, "generator", DEFAULT_GENERATOR_INSTRUCTIONS)
    return sync_failure_patterns(db, active.id)


@router.post("/evolve", response_model=EvolutionStarted, status_code=status.HTTP_202_ACCEPTED)
def evolve(admin: AdminUser, service: EvolutionServiceDep, background: BackgroundTasks) -> EvolutionStarted:
    background.add_task(service.run, get_settings().evolution_min_occurrences)
    return EvolutionStarted(status="started",
                            message="Self-evolution cycle started. Refresh in about a minute to see the result.")


@router.post("/prompts/{component}/rollback", response_model=PromptVersionOut)
def rollback(component: Literal["generator"], admin: AdminUser, db: DbSession,
             body: RollbackRequest | None = None) -> PromptVersion:
    return rollback_generator_prompt(db, body.to_version if body else None)
