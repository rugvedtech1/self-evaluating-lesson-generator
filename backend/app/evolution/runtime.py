"""Builds the real validator (Generator + Evaluator models) and the evolution service used by API and CLI."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import lru_cache

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import session_scope as default_session_scope
from app.evaluator.engine import LessonEvaluator
from app.evaluator.llm import LangChainLessonJudge
from app.evolution.cycle import EvolutionOutcome, Validator, run_evolution_cycle
from app.evolution.validation import validate_generator_prompt
from app.generator.llm import LangChainLessonGenerator
from app.llm.factory import build_chat_model

logger = logging.getLogger(__name__)


def build_validator() -> Validator:
    settings = get_settings()
    generator = LangChainLessonGenerator(
        build_chat_model("generator", temperature=0.4, max_tokens=settings.generator_max_tokens))
    evaluator = LessonEvaluator(LangChainLessonJudge(
        build_chat_model("evaluator", temperature=0, max_tokens=settings.evaluator_max_tokens)))
    return lambda prompt_text: validate_generator_prompt(prompt_text, generator, evaluator)


class EvolutionService:
    def __init__(self, validator_factory: Callable[[], Validator] = build_validator,
                 session_scope: Callable[[], AbstractContextManager[Session]] = default_session_scope) -> None:
        self._validator_factory = validator_factory
        self._session_scope = session_scope

    def run(self, min_occurrences: int) -> EvolutionOutcome | None:
        try:
            outcome = run_evolution_cycle(self._session_scope, self._validator_factory(), min_occurrences)
        except Exception:
            logger.exception("Self-evolution cycle failed")
            return None
        logger.info("Self-evolution cycle finished", extra={"context": outcome.model_dump()})
        return outcome


@lru_cache
def get_evolution_service() -> EvolutionService:
    return EvolutionService()
