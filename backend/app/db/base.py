"""SQLAlchemy declarative base and shared column helpers."""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Uuid, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names (must match the names used in Alembic migrations).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    """UUID primary key, generated in Python (and by Postgres as a fallback)."""
    return mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )


def user_fk() -> Mapped[uuid.UUID]:
    """Owner column present on every user-owned table (used by ownership checks and RLS)."""
    return mapped_column(Uuid, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)


def sql_in(column: str, values: Iterable[str]) -> str:
    """Build a CHECK expression such as: status IN ('a', 'b')."""
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"
