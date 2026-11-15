"""Initial schema: users' chats, messages, learner profiles, lesson runs/versions,
evaluations, plus system-wide failure patterns and prompt versions. Enables RLS.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copies of allowed values (migrations must not import from app models).
CHAT_STATUSES = ("intake", "awaiting_confirmation", "generating", "completed", "failed")
MESSAGE_ROLES = ("user", "assistant", "system")
LESSON_RUN_STATUSES = ("pending", "running", "approved", "rejected", "error")
EVALUATION_STATUSES = ("PASS", "FAIL")
PROMPT_COMPONENTS = ("intake", "generator", "evaluator")
PROMPT_STATUSES = ("draft", "validating", "active", "retired", "rejected")
FAILURE_PATTERN_STATUSES = ("open", "addressed", "dismissed")

# Tables holding one user's private data: owner column used by RLS policies.
USER_TABLES = {
    "profiles": "id",
    "chats": "user_id",
    "messages": "user_id",
    "chat_profiles": "user_id",
    "lesson_runs": "user_id",
    "lesson_versions": "user_id",
    "evaluations": "user_id",
}
# System tables: RLS enabled with NO policies => unreachable through Supabase's public Data API.
SYSTEM_TABLES = ("failure_patterns", "prompt_versions", "alembic_version")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _id() -> sa.Column:
    return sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str, default: str = "now()") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text(default))


def _user_id(table: str) -> list:
    return [
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["profiles.id"], name=f"fk_{table}_user_id_profiles", ondelete="CASCADE"),
    ]


def upgrade() -> None:
    # ---------------- profiles (linked to Supabase Auth) ----------------
    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_profiles"),
    )
    op.create_foreign_key(
        "fk_profiles_id_users", "profiles", "users", ["id"], ["id"],
        referent_schema="auth", ondelete="CASCADE",
    )

    # ---------------- prompt_versions (system) ----------------
    op.create_table(
        "prompt_versions",
        _id(),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("validation_report", postgresql.JSONB(), nullable=True),
        _ts("created_at"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_versions"),
        sa.ForeignKeyConstraint(["parent_version_id"], ["prompt_versions.id"],
                                name="fk_prompt_versions_parent_version_id_prompt_versions", ondelete="SET NULL"),
        sa.UniqueConstraint("component", "version", name="uq_prompt_versions_component_version"),
        sa.CheckConstraint(_in("component", PROMPT_COMPONENTS), name="ck_prompt_versions_component_valid"),
        sa.CheckConstraint(_in("status", PROMPT_STATUSES), name="ck_prompt_versions_status_valid"),
        sa.CheckConstraint("version >= 1", name="ck_prompt_versions_version_positive"),
    )
    op.create_index("ux_prompt_versions_one_active", "prompt_versions", ["component"],
                    unique=True, postgresql_where=sa.text("status = 'active'"))

    # ---------------- failure_patterns (system, no user data) ----------------
    op.create_table(
        "failure_patterns",
        _id(),
        sa.Column("criterion", sa.Text(), nullable=False),
        sa.Column("pattern_key", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("resolved_by_prompt_id", sa.Uuid(), nullable=True),
        _ts("first_seen_at"),
        _ts("last_seen_at"),
        sa.PrimaryKeyConstraint("id", name="pk_failure_patterns"),
        sa.ForeignKeyConstraint(["resolved_by_prompt_id"], ["prompt_versions.id"],
                                name="fk_failure_patterns_resolved_by_prompt_id_prompt_versions", ondelete="SET NULL"),
        sa.UniqueConstraint("criterion", "pattern_key", name="uq_failure_patterns_criterion_pattern_key"),
        sa.CheckConstraint(_in("status", FAILURE_PATTERN_STATUSES), name="ck_failure_patterns_status_valid"),
        sa.CheckConstraint("occurrence_count >= 0", name="ck_failure_patterns_occurrence_count_valid"),
    )

    # ---------------- chats ----------------
    op.create_table(
        "chats",
        _id(),
        *_user_id("chats"),
        sa.Column("title", sa.Text(), nullable=False, server_default="New chat"),
        sa.Column("status", sa.Text(), nullable=False, server_default="intake"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chats"),
        sa.CheckConstraint(_in("status", CHAT_STATUSES), name="ck_chats_status_valid"),
    )
    op.create_index("ix_chats_user_id_updated_at", "chats", ["user_id", "updated_at"])

    # ---------------- messages ----------------
    op.create_table(
        "messages",
        _id(),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        *_user_id("messages"),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="chat"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at", default="clock_timestamp()"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], name="fk_messages_chat_id_chats", ondelete="CASCADE"),
        sa.CheckConstraint(_in("role", MESSAGE_ROLES), name="ck_messages_role_valid"),
    )
    op.create_index("ix_messages_chat_id_created_at", "messages", ["chat_id", "created_at"])

    # ---------------- chat_profiles (one learner profile per chat) ----------------
    op.create_table(
        "chat_profiles",
        _id(),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        *_user_id("chat_profiles"),
        sa.Column("topic", sa.Text(), nullable=True),
        sa.Column("education_level", sa.Text(), nullable=True),
        sa.Column("english_proficiency", sa.Text(), nullable=True),
        sa.Column("technical_background", sa.Text(), nullable=True),
        sa.Column("ai_knowledge", sa.Text(), nullable=True),
        sa.Column("preferred_style", sa.Text(), nullable=True),
        sa.Column("additional_notes", sa.Text(), nullable=True),
        sa.Column("is_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chat_profiles"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], name="fk_chat_profiles_chat_id_chats", ondelete="CASCADE"),
        sa.UniqueConstraint("chat_id", name="uq_chat_profiles_chat_id"),
    )

    # ---------------- lesson_runs ----------------
    op.create_table(
        "lesson_runs",
        _id(),
        sa.Column("chat_id", sa.Uuid(), nullable=False),
        *_user_id("lesson_runs"),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("topic_key", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("generator_prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("evaluator_prompt_version_id", sa.Uuid(), nullable=True),
        sa.Column("final_attempt_number", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_lesson_runs"),
        sa.ForeignKeyConstraint(["chat_id"], ["chats.id"], name="fk_lesson_runs_chat_id_chats", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generator_prompt_version_id"], ["prompt_versions.id"],
                                name="fk_lesson_runs_generator_prompt_version_id_prompt_versions", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["evaluator_prompt_version_id"], ["prompt_versions.id"],
                                name="fk_lesson_runs_evaluator_prompt_version_id_prompt_versions", ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", LESSON_RUN_STATUSES), name="ck_lesson_runs_status_valid"),
        sa.CheckConstraint("max_attempts BETWEEN 1 AND 3", name="ck_lesson_runs_max_attempts_valid"),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND max_attempts", name="ck_lesson_runs_attempt_count_valid"),
    )
    op.create_index("ix_lesson_runs_chat_id", "lesson_runs", ["chat_id"])

    # ---------------- lesson_versions ----------------
    op.create_table(
        "lesson_versions",
        _id(),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        *_user_id("lesson_versions"),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("generator_feedback", sa.Text(), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_lesson_versions"),
        sa.ForeignKeyConstraint(["run_id"], ["lesson_runs.id"], name="fk_lesson_versions_run_id_lesson_runs", ondelete="CASCADE"),
        sa.UniqueConstraint("run_id", "attempt_number", name="uq_lesson_versions_run_id_attempt_number"),
        sa.CheckConstraint("attempt_number BETWEEN 1 AND 3", name="ck_lesson_versions_attempt_number_valid"),
    )

    # ---------------- evaluations ----------------
    op.create_table(
        "evaluations",
        _id(),
        sa.Column("lesson_version_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        *_user_id("evaluations"),
        sa.Column("overall_status", sa.Text(), nullable=False),
        sa.Column("criteria_results", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("failed_criteria", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("feedback_for_generator", sa.Text(), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_evaluations"),
        sa.ForeignKeyConstraint(["lesson_version_id"], ["lesson_versions.id"],
                                name="fk_evaluations_lesson_version_id_lesson_versions", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["lesson_runs.id"], name="fk_evaluations_run_id_lesson_runs", ondelete="CASCADE"),
        sa.UniqueConstraint("lesson_version_id", name="uq_evaluations_lesson_version_id"),
        sa.CheckConstraint(_in("overall_status", EVALUATION_STATUSES), name="ck_evaluations_overall_status_valid"),
    )
    op.create_index("ix_evaluations_run_id", "evaluations", ["run_id"])

    # ---------------- Row-level security ----------------
    for table, owner_column in USER_TABLES.items():
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f'CREATE POLICY "{table}_owner_all" ON public.{table} '
            f"FOR ALL TO authenticated "
            f"USING ({owner_column} = (select auth.uid())) "
            f"WITH CHECK ({owner_column} = (select auth.uid()))"
        )
    for table in SYSTEM_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE public.alembic_version DISABLE ROW LEVEL SECURITY")
    for table in ("evaluations", "lesson_versions", "lesson_runs", "chat_profiles",
                  "messages", "chats", "failure_patterns", "prompt_versions", "profiles"):
        op.drop_table(table)  # also drops that table's policies and indexes
