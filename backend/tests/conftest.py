"""Shared Pytest fixtures for backend tests."""

import os
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import urlparse

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, get_settings
from app.core.security import TokenVerifier
from app.main import create_app
from app.models import Profile

BACKEND_DIR = PROJECT_ROOT / "backend"


# ------------------------------------------------------------------ API client
@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A TestClient for a fresh app configured for the 'test' environment."""
    monkeypatch.setenv("APP_ENV", "test")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_settings.cache_clear()


# ------------------------------------------------------------- JWT test keys
# A key pair generated per test run: lets us mint "Supabase-like" tokens offline.
TEST_ISSUER = "https://test-project.supabase.co/auth/v1"
TEST_AUDIENCE = "authenticated"
_SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def make_token() -> Callable[..., str]:
    """Create a signed access token. Override any claim; pass claim=None to remove it."""

    def _make(*, key: Any = None, algorithm: str = "ES256", **overrides: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(uuid.uuid4()),
            "email": "learner@example.com",
            "role": "authenticated",
            "aud": TEST_AUDIENCE,
            "iss": TEST_ISSUER,
            "iat": now,
            "exp": now + 3600,
            "session_id": str(uuid.uuid4()),
        }
        claims.update(overrides)
        claims = {name: value for name, value in claims.items() if value is not None}
        return jwt.encode(claims, key if key is not None else _SIGNING_KEY,
                          algorithm=algorithm, headers={"kid": "test-kid"})

    return _make


@pytest.fixture
def token_verifier() -> TokenVerifier:
    public_key = _SIGNING_KEY.public_key()
    return TokenVerifier(issuer=TEST_ISSUER, audience=TEST_AUDIENCE, key_resolver=lambda _token: public_key)


# ------------------------------------------------------------- test database
# Minimal stand-in for what Supabase provides, so our real migration runs on plain Postgres.
SUPABASE_STUB_SQL = """
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END
$$;
CREATE SCHEMA auth;
CREATE TABLE auth.users (id uuid PRIMARY KEY, email text);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS
  $fn$ SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $fn$;
GRANT USAGE ON SCHEMA auth TO anon, authenticated;
GRANT USAGE ON SCHEMA public TO anon, authenticated;
-- Like Supabase: API roles get table privileges by default; RLS is what restricts rows.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO anon, authenticated;
"""


def _test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or dotenv_values(PROJECT_ROOT / ".env").get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set: start the Docker test database.")
    host = urlparse(url.replace("+psycopg", "")).hostname
    if host not in {"localhost", "127.0.0.1"}:
        pytest.fail(f"Refusing to run destructive DB tests against non-local host {host!r}.")
    return url


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """Fresh schema built by our real migrations (and proves downgrade works)."""
    url = _test_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
            conn.exec_driver_sql("DROP SCHEMA IF EXISTS auth CASCADE")
            conn.exec_driver_sql("CREATE SCHEMA public")
            conn.exec_driver_sql(SUPABASE_STUB_SQL)
    except OperationalError:
        pytest.skip("Test database not reachable: is the Docker container running?")

    cfg = _alembic_config(url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")  # round-trip: downgrade must work too
    command.upgrade(cfg, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after each test (tests stay isolated)."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def make_auth_user(db_session: Session) -> Callable[..., uuid.UUID]:
    """Create a fake Supabase Auth user (auth.users row only, no profile)."""

    def _make(email: str | None = None) -> uuid.UUID:
        user_id = uuid.uuid4()
        db_session.execute(text("INSERT INTO auth.users (id, email) VALUES (:id, :email)"),
                           {"id": user_id, "email": email or f"user-{user_id.hex[:8]}@example.com"})
        return user_id

    return _make


@pytest.fixture
def make_user(db_session: Session, make_auth_user: Callable[..., uuid.UUID]) -> Callable[..., uuid.UUID]:
    """Create a fake Supabase Auth user plus its application profile."""

    def _make(email: str | None = None) -> uuid.UUID:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        user_id = make_auth_user(email)
        db_session.add(Profile(id=user_id, email=email))
        db_session.flush()
        return user_id

    return _make
