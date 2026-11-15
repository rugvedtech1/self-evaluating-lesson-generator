"""Intake Assistant conversation behaviour, end to end against the database (fake LLM)."""

import pytest
from sqlalchemy import func, select

from app.core.exceptions import InvalidOperationError, LLMUnavailableError, NotFoundError
from app.intake.fields import NOT_SPECIFIED
from app.intake.service import IntakeAssistant, confirm_profile
from app.models import Message
from app.services import chats as chat_svc
from app.services import learner_profiles as profile_svc

pytestmark = pytest.mark.db

REST_OF_PROFILE = {
    "education_level": "Undergraduate", "english_proficiency": "Fluent",
    "technical_background": "Some Python", "ai_knowledge": "Uses ChatGPT",
    "preferred_style": "Real-life analogies",
}


@pytest.fixture
def ctx(db_session, make_user, fake_intake_llm):
    alice = make_user()
    chat = chat_svc.create_chat(db_session, alice)
    assistant = IntakeAssistant(fake_intake_llm)

    def send(text: str):
        return assistant.handle_user_message(db_session, alice, chat.id, text)

    return alice, chat, send, fake_intake_llm


def _message_count(db, chat_id) -> int:
    return db.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat_id))


def test_topic_captured_then_next_missing_field_asked(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="Introduction to RAG")
    result = send("I want to learn Introduction to RAG")
    assert result.profile.topic == "Introduction to RAG"
    assert result.assistant_message.kind == "intake_question"
    assert result.assistant_message.payload == {"intake_field": "education_level"}
    assert result.chat.status == "intake"


def test_message_with_several_facts_skips_those_questions(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG", education_level="Undergraduate", english_proficiency="Fluent")
    result = send("RAG please. I'm an undergrad and fluent in English.")
    assert result.assistant_message.payload == {"intake_field": "technical_background"}


def test_full_conversation_never_repeats_a_question(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG")
    send("RAG")
    for name, value in REST_OF_PROFILE.items():
        llm.queue(**{name: value})
        result = send(value)
    assert llm.asked_fields == list(REST_OF_PROFILE)
    assert len(llm.asked_fields) == len(set(llm.asked_fields))
    assert result.assistant_message.kind == "profile_summary"
    assert result.chat.status == "awaiting_confirmation"


def test_dont_know_is_recorded_and_not_asked_again(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG")
    send("RAG")
    llm.queue(education_level=NOT_SPECIFIED)
    result = send("I'd rather not say")
    assert result.profile.education_level == NOT_SPECIFIED
    assert llm.asked_fields == ["education_level", "english_proficiency"]


def test_unanswered_question_given_up_after_two_asks(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG")
    send("RAG")
    send("hmm")          # no answer -> asked once more
    result = send("ok")  # still nothing -> recorded as not specified, move on
    assert llm.asked_fields == ["education_level", "education_level", "english_proficiency"]
    assert result.profile.education_level == NOT_SPECIFIED


def test_summary_shows_stored_values_without_llm_question(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="Introduction to RAG", **REST_OF_PROFILE)
    result = send("Everything at once")
    assert result.assistant_message.kind == "profile_summary"
    assert "Real-life analogies" in result.assistant_message.content
    assert llm.asked_fields == []


def test_confirming_by_message_confirms_profile(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG", **REST_OF_PROFILE)
    send("Everything at once")
    llm.queue(confirms=True)
    result = send("Yes, that's right")
    assert result.chat.status == "generating"
    assert result.profile.is_confirmed is True
    assert result.assistant_message.kind == "profile_confirmed"


def test_correction_after_summary_produces_new_summary(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG", **REST_OF_PROFILE)
    send("Everything at once")
    llm.queue(preferred_style="Step-by-step")
    result = send("Actually I prefer step-by-step")
    assert result.assistant_message.kind == "profile_summary"
    assert "Step-by-step" in result.assistant_message.content
    assert result.chat.status == "awaiting_confirmation"


def test_extraction_failure_writes_nothing(ctx, db_session) -> None:
    _, chat, send, llm = ctx
    llm.extract_error = LLMUnavailableError("down")
    with pytest.raises(LLMUnavailableError):
        send("I want to learn RAG")
    assert _message_count(db_session, chat.id) == 0


def test_question_failure_writes_nothing(ctx, db_session) -> None:
    alice, chat, send, llm = ctx
    llm.queue(topic="RAG")
    llm.ask_error = LLMUnavailableError("down")
    with pytest.raises(LLMUnavailableError):
        send("I want to learn RAG")
    assert _message_count(db_session, chat.id) == 0
    assert profile_svc.get_learner_profile(db_session, alice, chat.id) is None


def test_other_users_chat_is_not_found(db_session, make_user, ctx, fake_intake_llm) -> None:
    _, chat, _, _ = ctx
    with pytest.raises(NotFoundError):
        IntakeAssistant(fake_intake_llm).handle_user_message(db_session, make_user(), chat.id, "hi")


def test_no_more_intake_after_confirmation(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG", **REST_OF_PROFILE)
    send("Everything at once")
    llm.queue(confirms=True)
    send("Yes")
    with pytest.raises(InvalidOperationError):
        send("one more thing")


def test_confirm_before_summary_is_rejected(ctx, db_session) -> None:
    alice, chat, _, _ = ctx
    with pytest.raises(InvalidOperationError):
        confirm_profile(db_session, alice, chat.id)


def test_inferred_fields_are_not_asked_about(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG")
    send("RAG")
    llm.queue(education_level="8th standard", technical_background="None (inferred)",
              ai_knowledge="Beginner (inferred)")
    send("I'm in 8th standard")
    llm.queue(english_proficiency="A little")
    result = send("a little")
    assert "technical_background" not in llm.asked_fields
    assert "ai_knowledge" not in llm.asked_fields
    assert result.assistant_message.payload == {"intake_field": "preferred_style"}


def test_direct_answer_is_never_marked_inferred(ctx) -> None:
    _, _, send, llm = ctx
    llm.queue(topic="RAG")
    send("RAG")                                  # assistant now asks about education_level
    llm.queue(education_level="12th (inferred)")  # LLM wrongly labels a direct answer
    result = send("12 th")
    assert result.profile.education_level == "12th"
