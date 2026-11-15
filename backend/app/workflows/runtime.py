"""Process-wide lesson workflow runtime: checkpointer pool + compiled graph, built on first use."""

import logging
import threading

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from app.core.config import get_settings
from app.db.session import DatabaseNotConfiguredError, session_scope
from app.evaluator.engine import LessonEvaluator
from app.evaluator.llm import LangChainLessonJudge
from app.generator.llm import LangChainLessonGenerator
from app.workflows.demo import DemoFlawGenerator
from app.llm.factory import build_chat_model
from app.workflows.checkpointer import create_checkpointer_pool
from app.workflows.lesson_graph import LessonWorkflowDeps, build_lesson_graph
from app.workflows.recovery import recover_interrupted_runs
from app.workflows.runner import LessonWorkflowRunner

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_runner: LessonWorkflowRunner | None = None
_pool: ConnectionPool | None = None


def get_lesson_runner() -> LessonWorkflowRunner:
    global _runner, _pool
    with _lock:
        if _runner is None:
            settings = get_settings()
            if settings.database_url is None:
                raise DatabaseNotConfiguredError("DATABASE_URL is not set. Add it to your .env file.")
            generator = DemoFlawGenerator(
                LangChainLessonGenerator(
                    build_chat_model("generator", temperature=0.4, max_tokens=settings.generator_max_tokens)),
                mode=settings.demo_flaw_mode, case_key=settings.demo_flaw_case)
            evaluator = LessonEvaluator(LangChainLessonJudge(
                build_chat_model("evaluator", temperature=0, max_tokens=settings.evaluator_max_tokens)))
            pool = create_checkpointer_pool(settings.database_url.get_secret_value())
            pool.open(wait=True, timeout=15)
            try:
                checkpointer = PostgresSaver(pool)
                checkpointer.setup()  # library-managed tables; idempotent
            except Exception:
                pool.close()
                raise
            graph = build_lesson_graph(
                LessonWorkflowDeps(session_scope=session_scope, generator=generator, evaluator=evaluator),
                checkpointer=checkpointer)
            _pool, _runner = pool, LessonWorkflowRunner(graph)
        return _runner


def recover_in_background() -> None:
    """Run at API startup (in a thread): resume runs interrupted by the previous shutdown."""
    try:
        count = recover_interrupted_runs(get_lesson_runner())
        logger.info("Interrupted lesson runs processed", extra={"context": {"count": count}})
    except Exception:
        logger.exception("Lesson run recovery failed")


def shutdown() -> None:
    global _runner, _pool
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool, _runner = None, None
