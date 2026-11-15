"""API tests for /chats with real ownership checks (two users, local Docker DB)."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_token_verifier
from app.core.security import TokenVerifier
from app.db.session import get_db
from app.main import create_app
from app.models import Message

pytestmark = pytest.mark.db


@pytest.fixture
def api(db_session: Session, token_verifier: TokenVerifier) -> Iterator[TestClient]:
    app = create_app()

    def _test_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[get_token_verifier] = lambda: token_verifier
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def alice(make_user, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user()))}"}


@pytest.fixture
def bob(make_user, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user()))}"}


def test_create_and_list_chat(api, alice) -> None:
    created = api.post("/chats", json={}, headers=alice)
    assert created.status_code == 201
    assert created.json()["title"] == "New chat"
    listed = api.get("/chats", headers=alice).json()
    assert [c["id"] for c in listed] == [created.json()["id"]]


def test_users_only_see_their_own_chats(api, alice, bob) -> None:
    api.post("/chats", json={"title": "Bob's private chat"}, headers=bob)
    assert api.get("/chats", headers=alice).json() == []


def test_other_users_chat_returns_404(api, alice, bob) -> None:
    bobs_id = api.post("/chats", json={}, headers=bob).json()["id"]
    assert api.get(f"/chats/{bobs_id}", headers=alice).status_code == 404
    assert api.patch(f"/chats/{bobs_id}", json={"title": "x"}, headers=alice).status_code == 404
    assert api.delete(f"/chats/{bobs_id}", headers=alice).status_code == 404


def test_post_message_and_reopen_chat(api, alice) -> None:
    chat_id = api.post("/chats", json={}, headers=alice).json()["id"]
    posted = api.post(f"/chats/{chat_id}/messages", json={"content": "I want to learn RAG"}, headers=alice)
    assert posted.status_code == 201
    assert posted.json()["role"] == "user"

    detail = api.get(f"/chats/{chat_id}", headers=alice).json()
    assert [m["content"] for m in detail["messages"]] == ["I want to learn RAG"]
    assert detail["chat"]["title"] == "I want to learn RAG"
    assert detail["learner_profile"] is None


def test_cannot_post_into_other_users_chat(api, alice, bob, db_session) -> None:
    bobs_id = api.post("/chats", json={}, headers=bob).json()["id"]
    response = api.post(f"/chats/{bobs_id}/messages", json={"content": "sneaky"}, headers=alice)
    assert response.status_code == 404
    count = db_session.scalar(select(func.count()).select_from(Message)
                              .where(Message.chat_id == uuid.UUID(bobs_id)))
    assert count == 0


def test_blank_message_rejected(api, alice) -> None:
    chat_id = api.post("/chats", json={}, headers=alice).json()["id"]
    assert api.post(f"/chats/{chat_id}/messages", json={"content": "   "}, headers=alice).status_code == 422


def test_rename_then_delete(api, alice) -> None:
    chat_id = api.post("/chats", json={}, headers=alice).json()["id"]
    assert api.patch(f"/chats/{chat_id}", json={"title": "RAG basics"}, headers=alice).json()["title"] == "RAG basics"
    assert api.delete(f"/chats/{chat_id}", headers=alice).status_code == 204
    assert api.get(f"/chats/{chat_id}", headers=alice).status_code == 404


def test_chats_require_authentication(api) -> None:
    assert api.get("/chats").status_code == 401
    assert api.post("/chats", json={}).status_code == 401


def test_invalid_chat_id_returns_422(api, alice) -> None:
    assert api.get("/chats/not-a-uuid", headers=alice).status_code == 422
