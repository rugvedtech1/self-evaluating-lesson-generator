"""API tests for /chats: ownership, intake, confirmation, lesson-run start (fake LLM + fake runner)."""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_intake_assistant, get_lesson_runner, get_token_verifier
from app.core.exceptions import LLMUnavailableError
from app.core.security import TokenVerifier
from app.db.session import get_db
from app.intake.service import IntakeAssistant
from app.main import create_app
from app.models import Message
from app.services import lessons as lesson_svc

pytestmark = pytest.mark.db

REST_OF_PROFILE = {
    "education_level": "Undergraduate", "english_proficiency": "Fluent",
    "technical_background": "Some Python", "ai_knowledge": "Uses ChatGPT",
    "preferred_style": "Real-life analogies",
}


@dataclass
class FakeRunner:
    """Records which runs were handed to the background (does not call any LLM)."""

    started: list[uuid.UUID] = field(default_factory=list)

    def run(self, run_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.started.append(run_id)


@pytest.fixture
def fake_runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def api(db_session: Session, token_verifier: TokenVerifier, fake_intake_llm, fake_runner) -> Iterator[TestClient]:
    app = create_app()

    def _test_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = _test_db
    app.dependency_overrides[get_token_verifier] = lambda: token_verifier
    app.dependency_overrides[get_intake_assistant] = lambda: IntakeAssistant(fake_intake_llm)
    app.dependency_overrides[get_lesson_runner] = lambda: fake_runner
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def alice_id(make_user) -> uuid.UUID:
    return make_user()


@pytest.fixture
def alice(alice_id, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(alice_id))}"}


@pytest.fixture
def bob(make_user, make_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(sub=str(make_user()))}"}


def _new_chat(api: TestClient, headers: dict[str, str]) -> str:
    return api.post("/chats", json={}, headers=headers).json()["id"]


def _confirmed_chat(api: TestClient, headers: dict[str, str], llm) -> str:
    chat_id = _new_chat(api, headers)
    llm.queue(topic="Introduction to RAG", **REST_OF_PROFILE)
    api.post(f"/chats/{chat_id}/messages", json={"content": "all about me"}, headers=headers)
    return chat_id


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
    assert api.post(f"/chats/{bobs_id}/lesson-runs", headers=alice).status_code == 404


def test_message_gets_intake_reply_and_chat_reopens_with_history(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.queue(topic="Introduction to RAG")
    turn = api.post(f"/chats/{chat_id}/messages", json={"content": "I want to learn RAG"}, headers=alice)
    assert turn.status_code == 201
    body = turn.json()
    assert body["user_message"]["role"] == "user"
    assert body["assistant_message"]["kind"] == "intake_question"
    assert body["learner_profile"]["topic"] == "Introduction to RAG"
    assert body["lesson_run"] is None

    detail = api.get(f"/chats/{chat_id}", headers=alice).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["chat"]["title"] == "I want to learn RAG"
    assert detail["latest_run"] is None


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


def test_confirming_starts_lesson_generation_in_background(api, alice, fake_intake_llm, fake_runner) -> None:
    chat_id = _confirmed_chat(api, alice, fake_intake_llm)
    confirmed = api.post(f"/chats/{chat_id}/profile/confirm", headers=alice)
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["chat"]["status"] == "generating"
    assert body["learner_profile"]["is_confirmed"] is True
    assert body["lesson_run"]["status"] == "running"
    assert body["lesson_run"]["topic_key"] == "intro_to_rag"
    assert fake_runner.started == [uuid.UUID(body["lesson_run"]["id"])]

    late = api.post(f"/chats/{chat_id}/messages", json={"content": "more"}, headers=alice)
    assert late.status_code == 409


def test_confirming_in_words_also_starts_generation(api, alice, fake_intake_llm, fake_runner) -> None:
    chat_id = _confirmed_chat(api, alice, fake_intake_llm)
    fake_intake_llm.queue(confirms=True)
    turn = api.post(f"/chats/{chat_id}/messages", json={"content": "Yes, correct"}, headers=alice).json()
    assert turn["chat"]["status"] == "generating"
    assert turn["lesson_run"] is not None
    assert len(fake_runner.started) == 1


def test_confirm_too_early_returns_409(api, alice) -> None:
    chat_id = _new_chat(api, alice)
    assert api.post(f"/chats/{chat_id}/profile/confirm", headers=alice).status_code == 409


def test_start_lesson_requires_confirmed_profile(api, alice) -> None:
    chat_id = _new_chat(api, alice)
    assert api.post(f"/chats/{chat_id}/lesson-runs", headers=alice).status_code == 409


def test_start_lesson_rejected_while_one_is_running(api, alice, fake_intake_llm) -> None:
    chat_id = _confirmed_chat(api, alice, fake_intake_llm)
    api.post(f"/chats/{chat_id}/profile/confirm", headers=alice)
    response = api.post(f"/chats/{chat_id}/lesson-runs", headers=alice)
    assert response.status_code == 409
    assert "already" in response.json()["detail"]


def test_chat_detail_includes_attempts_evaluations_and_phase(api, alice, alice_id, fake_intake_llm,
                                                             db_session) -> None:
    chat_id = _confirmed_chat(api, alice, fake_intake_llm)
    run_id = uuid.UUID(api.post(f"/chats/{chat_id}/profile/confirm", headers=alice).json()["lesson_run"]["id"])
    version = lesson_svc.add_lesson_version(db_session, alice_id, run_id, content="# Lesson\n\nHello")
    lesson_svc.add_evaluation(db_session, alice_id, version.id, overall_status="FAIL",
                              criteria_results=[{"criterion": "jargon_explanation", "status": "FAIL"}],
                              failed_criteria=["jargon_explanation"], feedback_for_generator="Explain embeddings.")

    run = api.get(f"/chats/{chat_id}", headers=alice).json()["latest_run"]
    assert run["id"] == str(run_id)
    assert (run["phase"], run["current_attempt"]) == ("improving", 2)
    attempt = run["attempts"][0]
    assert attempt["attempt_number"] == 1 and attempt["content"].startswith("# Lesson")
    assert attempt["evaluation"]["failed_criteria"] == ["jargon_explanation"]
    assert attempt["evaluation"]["feedback_for_generator"] == "Explain embeddings."


def test_llm_outage_returns_503_and_saves_nothing(api, alice, fake_intake_llm) -> None:
    chat_id = _new_chat(api, alice)
    fake_intake_llm.extract_error = LLMUnavailableError("The AI service is temporarily unavailable.")
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
