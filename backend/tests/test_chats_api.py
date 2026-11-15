"""API tests for /chats: ownership, intake conversation, confirmation, LLM outage handling."""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_intake_assistant, get_token_verifier
from app.core.exceptions import LLMUnavailableError
from app.core.security import TokenVerifier
from app.db.session import get_db
from app.intake.service import IntakeAssistant
from app.main import create_app
from app.models import Message

pytestmark = pytest.mark.db

REST_OF_PROFILE = {
    "education_level": "Undergraduate", "english_proficiency": "Fluent",
    "technical_background": "Some Python", "ai_knowledge": "Uses ChatGPT",
    "preferred_style": "Real-life analogies",
}


@pytest.fixture
def api(db_session: Session, token_verifier: TokenVerifier, fake_intake_llm) -> Iterator[TestClient]:
    app = create_app()

    def _test_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[get_token_verifier] = lambda: token_verifier
    app.dependency_overrides[get_intake_assistant] = lambda: IntakeAssistant(fake_intake_llm)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def alice(make_user, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user()))}"}


@pytest.fixture
def bob(make_user, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user()))}"}


def _new_chat(api: TestClient, headers: dict[str, str]) -> str:
    return api.post("/chats", json={}, headers=headers).json()["id"]


def test_create_and_list_chat(api, alice) -> None:
    created = api.post("/chats", json={}, headers=alice)
    assert created.status_code == 201
    assert created.json()["title"] == "New chat"
    assert [c["id"] for c in api.get("/chats", headers=alice).json()] == [created.json()["id"]]


def test_users_only_see_their_own_chats(api, alice, bob) -> None:
    api.post("/chats", json={"title": "Bob's private chat"}, headers=bob)
    assert api.get("/chats", headers=alice).json() == []


def test_other_users_chat_returns_404(api, alice, bob) -> None:
    bobs_id = _new_chat(api, bob)
    assert api.get(f"/chats/{bobs_id}", headers=alice).status_code == 404
    assert api.patch(f"/chats/{bobs_id}", json={"title": "x"}, headers=alice).status_code == 404
    assert api.delete(f"/chats/{bobs_id}", headers=alice).status_code == 404
    assert api.post(f"/chats/{bobs_id}/profile/confirm", headers=alice).status_code == 404


def test_message_gets_intake_reply_and_chat_reopens_with_history(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.queue(topic="Introduction to RAG")
    turn = api.post(f"/chats/{chat_id}/messages", json={"content": "I want to learn RAG"}, headers=alice)
    assert turn.status_code == 201
    body = turn.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["kind"] == "intake_question"
    assert body["learner_profile"]["topic"] == "Introduction to RAG"

    detail = api.get(f"/chats/{chat_id}", headers=alice).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["chat"]["title"] == "I want to learn RAG"
    assert detail["learner_profile"]["topic"] == "Introduction to RAG"


def test_cannot_post_into_other_users_chat(api, alice, bob, db_session) -> None:
    bobs_id = _new_chat(api, bob)
    response = api.post(f"/chats/{bobs_id}/messages", json={"content": "sneaky"}, headers=alice)
    assert response.status_code == 404
    count = db_session.scalar(select(func.count()).select_from(Message)
                              .where(Message.chat_id == uuid.UUID(bobs_id)))
    assert count == 0


def test_blank_message_rejected(api, alice) -> None:
    chat_id = _new_chat(api, alice)
    assert api.post(f"/chats/{chat_id}/messages", json={"content": "   "}, headers=alice).status_code == 422


def test_full_intake_then_confirm_with_button(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.queue(topic="RAG", **REST_OF_PROFILE)
    turn = api.post(f"/chats/{chat_id}/messages", json={"content": "all about me"}, headers=alice).json()
    assert turn["chat"]["status"] == "awaiting_confirmation"

    confirmed = api.post(f"/chats/{chat_id}/profile/confirm", headers=alice)
    assert confirmed.status_code == 200
    assert confirmed.json()["chat"]["status"] == "generating"
    assert confirmed.json()["learner_profile"]["is_confirmed"] is True

    late = api.post(f"/chats/{chat_id}/messages", json={"content": "more"}, headers=alice)
    assert late.status_code == 409


def test_confirm_too_early_returns_409(api, alice) -> None:
    chat_id = _new_chat(api, alice)
    assert api.post(f"/chats/{chat_id}/profile/confirm", headers=alice).status_code == 409


def test_llm_outage_returns_503_and_saves_nothing(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.extract_error = LLMUnavailableError("The assistant is temporarily unavailable.")
    response = api.post(f"/chats/{chat_id}/messages", json={"content": "hello"}, headers=alice)
    assert response.status_code == 503
    assert api.get(f"/chats/{chat_id}", headers=alice).json()["messages"] == []


def test_rename_then_delete(api, alice) -> None:
    chat_id = _new_chat(api, alice)
    assert api.patch(f"/chats/{chat_id}", json={"title": "RAG basics"}, headers=alice).json()["title"] == "RAG basics"
    assert api.delete(f"/chats/{chat_id}", headers=alice).status_code == 204
    assert api.get(f"/chats/{chat_id}", headers=alice).status_code == 404


def test_chats_require_authentication(api) -> None:
    assert api.get("/chats").status_code == 401
    assert api.post("/chats", json={}).status_code == 401


def test_invalid_chat_id_returns_422(api, alice) -> None:
    assert api.get("/chats/not-a-uuid", headers=alice).status_code == 422


def test_messages_endpoint_lists_history(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.queue(topic="RAG")
    api.post(f"/chats/{chat_id}/messages", json={"content": "RAG"}, headers=alice)
    assert len(api.get(f"/chats/{chat_id}/messages", headers=alice).json()) == 2
