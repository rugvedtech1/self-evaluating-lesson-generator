"""Private schema for LangGraph checkpoints (tables are created by PostgresSaver.setup()).

Revision ID: 0002_langgraph_schema
Revises: 0001_initial_schema
Create Date: 2026-11-15
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_langgraph_schema"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS langgraph")
    # Not part of Supabase's Data API, and API roles get no access at all.
    op.execute("REVOKE ALL ON SCHEMA langgraph FROM PUBLIC, anon, authenticated")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS langgraph CASCADE")
