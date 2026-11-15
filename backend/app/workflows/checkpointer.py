"""LangGraph durable workflow state, stored by PostgresSaver in the private `langgraph` schema.

Run once per database (idempotent) to let LangGraph create/upgrade its own tables:
    PYTHONPATH=backend python -m app.workflows.checkpointer
"""

from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.config import get_settings

CHECKPOINT_SCHEMA = "langgraph"


def to_psycopg_url(url: str) -> str:
    """SQLAlchemy URLs name the driver ('postgresql+psycopg://'); psycopg wants 'postgresql://'."""
    for prefix in ("postgresql+psycopg://", "postgres+psycopg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _use_checkpoint_schema(conn: Connection[Any]) -> None:
    # Runs on every new pooled connection: LangGraph's unqualified table names land in our schema.
    conn.execute(f"SET search_path TO {CHECKPOINT_SCHEMA}")


def create_checkpointer_pool(database_url: str, max_size: int = 4) -> ConnectionPool:
    """Connection pool configured as PostgresSaver requires (autocommit + dict rows)."""
    return ConnectionPool(
        conninfo=to_psycopg_url(database_url),
        min_size=1,
        max_size=max_size,
        kwargs={"autocommit": True, "row_factory": dict_row},
        configure=_use_checkpoint_schema,
        open=False,  # opened explicitly / via `with`
    )


def setup_checkpointer(database_url: str) -> None:
    """Let LangGraph create or migrate its own checkpoint tables (safe to run repeatedly)."""
    with create_checkpointer_pool(database_url, max_size=1) as pool:
        PostgresSaver(pool).setup()


def main() -> None:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL is not set. Add it to your .env file.")
    setup_checkpointer(settings.database_url.get_secret_value())
    print(f"LangGraph checkpointer tables are ready in schema '{CHECKPOINT_SCHEMA}'.")


if __name__ == "__main__":
    main()
