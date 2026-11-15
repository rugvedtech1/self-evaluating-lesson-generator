"""Alembic environment: connects using our Settings, never a URL stored in a file."""

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base

config = context.config
target_metadata = Base.metadata


def get_url() -> str:
    # Tests pass a URL programmatically; normal use reads DATABASE_URL from settings.
    override = config.attributes.get("database_url")
    if override:
        return override
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not set. Add it to your .env file.")
    return settings.database_url.get_secret_value()


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(get_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
