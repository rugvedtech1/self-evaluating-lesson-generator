"""API tests for /auth/* with a fake Supabase client and the local Docker database."""

import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_auth_client, get_token_verifier
from app.core.exceptions import AuthRejectedError, AuthServiceUnavailableError
from app.core.security import TokenVerifier
from app.db.session import get_db
from app.main import create_app
from app.models import Profile
from app.services.supabase_auth import AuthSession, AuthUser, SignUpResult

pytestmark = pytest.mark.db

EMAIL = "learner@example.com"
PASSWORD = "correct-horse-battery"


@dataclass
class FakeAuthClient:
    """Stands in for Supabase Auth. Set `error` to simulate a failure."""

    user_id: uuid.UUID
    email: str = EMAIL
    error: Exception | None = None
    confirmation_required: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    def _session(self) -> AuthSession:
        return AuthSession(access_token="access-token", refresh_token="refresh-token", expires_in=3600,
                           token_type="bearer", user=AuthUser(id=self.user_id, email=self.email))

    def _maybe_fail(self) -> None:
        if self.error is not None:
            raise self.error

    def sign_up(self, email: str, password: str) -> SignUpResult:
        self.calls.append(("sign_up", email))
        self._maybe_fail()
        session = None if self.confirmation_required else self._session()
        return SignUpResult(user=AuthUser(id=self.user_id, email=email), session=session)

    def sign_in_with_password(self, email: str, password: str) -> AuthSession:
        self.calls.append(("sign_in", email))
        self._maybe_fail()
        return self._session()

    def refresh_session(self, refresh_token: str) -> AuthSession:
        self.calls.append(("refresh", refresh_token))
        self._maybe_fail()
        return self._session()

    def sign_out(self, access_token: str) -> None:
        self.calls.append(("sign_out", access_token))
        self._maybe_fail()


@pytest.fixture
def auth_user_id(make_auth_user: Callable[..., uuid.UUID]) -> uuid.UUID:
    return make_auth_user(EMAIL)


@pytest.fixture
def fake_auth(auth_user_id: uuid.UUID) -> FakeAuthClient:
    return FakeAuthClient(user_id=auth_user_id)


@pytest.fixture
def api(db_session: Session, fake_auth: FakeAuthClient, token_verifier: TokenVerifier) -> Iterator[TestClient]:
    app = create_app()

    def _test_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[get_auth_client] = lambda: fake_auth
    app.dependency_overrides[get_token_verifier] = lambda: token_verifier
    with TestClient(app) as test_client:
        yield test_client


def _profile_count(db: Session, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Profile).where(Profile.id == user_id))


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ signup
def test_signup_returns_session_and_creates_profile(api, db_session, auth_user_id) -> None:
    response = api.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 201
    body = response.json()
    assert body["session"]["access_token"] == "access-token"
    assert body["email_confirmation_required"] is False
    assert _profile_count(db_session, auth_user_id) == 1


def test_signup_reports_when_email_confirmation_required(api, fake_auth) -> None:
    fake_auth.confirmation_required = True
    body = api.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD}).json()
    assert body["session"] is None
    assert body["email_confirmation_required"] is True


def test_signup_rejects_invalid_email_without_calling_supabase(api, fake_auth) -> None:
    response = api.post("/auth/signup", json={"email": "not-an-email", "password": PASSWORD})
    assert response.status_code == 422
    assert fake_auth.calls == []


def test_signup_rejects_short_password(api, fake_auth) -> None:
    response = api.post("/auth/signup", json={"email": EMAIL, "password": "short"})
    assert response.status_code == 422
    assert fake_auth.calls == []


def test_signup_rejected_by_supabase_returns_400(api, fake_auth) -> None:
    fake_auth.error = AuthRejectedError("User already registered", 422)
    response = api.post("/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 400
    assert response.json()["detail"] == "User already registered"


# ------------------------------------------------------------------ login
def test_login_success_returns_tokens(api, db_session, auth_user_id) -> None:
    response = api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["refresh_token"] == "refresh-token"
    assert _profile_count(db_session, auth_user_id) == 1


def test_login_wrong_password_returns_401(api, fake_auth) -> None:
    fake_auth.error = AuthRejectedError("Invalid login credentials", 400)
    response = api.post("/auth/login", json={"email": EMAIL, "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid login credentials"


def test_auth_service_down_returns_503_not_401(api, fake_auth) -> None:
    fake_auth.error = AuthServiceUnavailableError("Could not reach the authentication service.")
    response = api.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 503


def test_refresh_returns_new_session(api, fake_auth) -> None:
    response = api.post("/auth/refresh", json={"refresh_token": "refresh-old"})
    assert response.status_code == 200
    assert ("refresh", "refresh-old") in fake_auth.calls


# ------------------------------------------------------------------ protected routes
def test_me_without_token_returns_401(api) -> None:
    response = api.get("/auth/me")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_with_garbage_token_returns_401(api) -> None:
    assert api.get("/auth/me", headers=_bearer("garbage")).status_code == 401


def test_me_with_expired_token_returns_401(api, make_token, auth_user_id) -> None:
    now = int(time.time())
    token = make_token(sub=str(auth_user_id), iat=now - 7200, exp=now - 3600)
    response = api.get("/auth/me", headers=_bearer(token))
    assert response.status_code == 401
    assert "expired" in response.json()["detail"]


def test_me_with_valid_token_returns_profile(api, make_token, db_session, auth_user_id) -> None:
    token = make_token(sub=str(auth_user_id), email=EMAIL)
    response = api.get("/auth/me", headers=_bearer(token))
    assert response.status_code == 200
    assert response.json()["id"] == str(auth_user_id)
    assert response.json()["email"] == EMAIL
    assert _profile_count(db_session, auth_user_id) == 1


def test_logout_revokes_session_at_supabase(api, make_token, fake_auth, auth_user_id) -> None:
    token = make_token(sub=str(auth_user_id))
    response = api.post("/auth/logout", headers=_bearer(token))
    assert response.status_code == 204
    assert ("sign_out", token) in fake_auth.calls


def test_logout_without_token_returns_401(api, fake_auth) -> None:
    assert api.post("/auth/logout").status_code == 401
    assert fake_auth.calls == []
