"""Process-wide lesson workflow runtime: checkpointer pool + compiled graph, built on first use."""

import threading

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

from app.core.config import get_settings
from app.db.session import DatabaseNotConfiguredError, session_scope
from app.generator.llm import LangChainLessonGenerator
from app.llm.factory import build_chat_model
from app.workflows.checkpointer import create_checkpointer_pool
from app.workflows.lesson_graph import LessonWorkflowDeps, build_lesson_graph
from app.workflows.runner import LessonWorkflowRunner

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
            generator = LangChainLessonGenerator(
                build_chat_model("generator", temperature=0.4, max_tokens=settings.generator_max_tokens)
            )
            pool = create_checkpointer_pool(settings.database_url.get_secret_value())
            pool.open(wait=True, timeout=15)
            try:
                checkpointer = PostgresSaver(pool)
                checkpointer.setup()  # library-managed tables; idempotent
            except Exception:
                pool.close()
                raise
            graph = build_lesson_graph(LessonWorkflowDeps(session_scope=session_scope, generator=generator),
                                       checkpointer=checkpointer)
            _pool, _runner = pool, LessonWorkflowRunner(graph)
        return _runner


def shutdown() -> None:
    global _runner, _pool
    with _lock:
        if _pool is not None:
            _pool.close()
        _pool, _runner = None, None
