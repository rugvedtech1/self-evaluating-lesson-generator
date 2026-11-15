"""/system API: anyone logged in can read anonymous learning data; only admins can change prompts."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_evolution_service, get_token_verifier
from app.core.config import get_settings
from app.db.session import get_db
from app.main import create_app
from app.services.prompts import activate_prompt, create_candidate_prompt, ensure_active_prompt

pytestmark = pytest.mark.db
ADMIN = "admin@example.com"


class FakeEvolution:
    def __init__(self) -> None:
        self.runs = []

    def run(self, min_occurrences: int) -> None:
        self.runs.append(min_occurrences)


@pytest.fixture
def evolution() -> FakeEvolution:
    return FakeEvolution()


@pytest.fixture
def api(db_session, token_verifier, evolution, monkeypatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ADMIN_EMAILS", ADMIN)
    get_settings.cache_clear()
    app = create_app()

    def _test_db():
        yield db_session

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[get_token_verifier] = lambda: token_verifier
    app.dependency_overrides[get_evolution_service] = lambda: evolution
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def _headers(make_user, make_token, email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user(email)), email=email)}"}


def test_reading_requires_login(api) -> None:
    assert api.get("/system/failure-patterns").status_code == 401


def test_any_user_can_list_prompt_versions(api, db_session, make_user, make_token) -> None:
    ensure_active_prompt(db_session, "generator", "BASE")
    body = api.get("/system/prompts/generator", headers=_headers(make_user, make_token, "learner@example.com")).json()
    assert [(p["version"], p["status"]) for p in body] == [(1, "active")]


def test_failure_patterns_expose_no_user_fields(api, make_user, make_token) -> None:
    response = api.get("/system/failure-patterns", headers=_headers(make_user, make_token, "learner@example.com"))
    assert response.status_code == 200
    for pattern in response.json():
        assert not {"user_id", "chat_id", "run_id"} & set(pattern)


def test_non_admin_cannot_start_evolution(api, make_user, make_token, evolution) -> None:
    response = api.post("/system/evolve", headers=_headers(make_user, make_token, "learner@example.com"))
    assert response.status_code == 403
    assert evolution.runs == []


def test_admin_starts_evolution_in_background(api, make_user, make_token, evolution) -> None:
    response = api.post("/system/evolve", headers=_headers(make_user, make_token, ADMIN))
    assert response.status_code == 202
    assert evolution.runs == [get_settings().evolution_min_occurrences]


def test_admin_can_roll_back(api, db_session, make_user, make_token) -> None:
    v1 = ensure_active_prompt(db_session, "generator", "BASE")
    activate_prompt(db_session, create_candidate_prompt(db_session, "generator", "NEW", parent=v1, change_reason="t"))
    response = api.post("/system/prompts/generator/rollback", json={}, headers=_headers(make_user, make_token, ADMIN))
    assert response.status_code == 200
    assert (response.json()["version"], response.json()["status"]) == (1, "active")
