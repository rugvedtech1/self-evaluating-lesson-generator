"""LangGraph PostgresSaver: private schema, no API-role access, state survives a 'restart'."""

import uuid
from collections.abc import Iterator
from typing import TypedDict

import pytest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.workflows.checkpointer import create_checkpointer_pool, setup_checkpointer, to_psycopg_url


def test_sqlalchemy_url_converted_for_psycopg() -> None:
    assert to_psycopg_url("postgresql+psycopg://u:p@h:5432/db?sslmode=require") == \
        "postgresql://u:p@h:5432/db?sslmode=require"
    assert to_psycopg_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"


@pytest.fixture(scope="session")
def checkpoint_url(migrated_engine: Engine) -> Iterator[str]:
    url = migrated_engine.url.render_as_string(hide_password=False)
    setup_checkpointer(url)
    yield url


class CounterState(TypedDict):
    count: int


def _build_graph(checkpointer: PostgresSaver):
    graph = StateGraph(CounterState)
    graph.add_node("increment", lambda state: {"count": state["count"] + 1})
    graph.add_edge(START, "increment")
    graph.add_edge("increment", END)
    return graph.compile(checkpointer=checkpointer)


@pytest.mark.db
def test_checkpoint_tables_live_only_in_private_schema(migrated_engine: Engine, checkpoint_url: str) -> None:
    with migrated_engine.connect() as conn:
        schemas = set(conn.execute(text(
            "SELECT DISTINCT table_schema FROM information_schema.tables WHERE table_name LIKE 'checkpoint%'"
        )).scalars())
    assert schemas == {"langgraph"}


@pytest.mark.db
def test_api_roles_cannot_read_checkpoints(migrated_engine: Engine, checkpoint_url: str) -> None:
    with migrated_engine.connect() as conn, conn.begin():
        conn.execute(text("SET LOCAL ROLE authenticated"))
        with pytest.raises(DBAPIError, match="permission denied"):
            conn.execute(text("SELECT count(*) FROM langgraph.checkpoints"))


@pytest.mark.db
def test_graph_state_survives_restart(checkpoint_url: str) -> None:
    config = {"configurable": {"thread_id": f"test-{uuid.uuid4()}"}}

    with create_checkpointer_pool(checkpoint_url) as pool:
        result = _build_graph(PostgresSaver(pool)).invoke({"count": 41}, config)
    assert result["count"] == 42

    # Brand-new pool + graph = simulated server restart: state must come back from Postgres.
    with create_checkpointer_pool(checkpoint_url) as pool:
        state = _build_graph(PostgresSaver(pool)).get_state(config)
    assert state.values["count"] == 42
