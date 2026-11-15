"""Learner profile services: partial updates, confirmation rules, ownership."""

import pytest

from app.core.exceptions import InvalidOperationError, NotFoundError
from app.services import chats as chat_svc
from app.services import learner_profiles as svc

pytestmark = pytest.mark.db


@pytest.fixture
def alice_chat(db_session, make_user):
    alice = make_user()
    return alice, chat_svc.create_chat(db_session, alice)


def test_profile_absent_until_created(db_session, alice_chat) -> None:
    alice, chat = alice_chat
    assert svc.get_learner_profile(db_session, alice, chat.id) is None


def test_upsert_creates_then_partially_updates(db_session, alice_chat) -> None:
    alice, chat = alice_chat
    svc.upsert_learner_profile(db_session, alice, chat.id, {"topic": "Introduction to RAG"})
    profile = svc.upsert_learner_profile(db_session, alice, chat.id, {"education_level": "Undergraduate"})
    assert profile.topic == "Introduction to RAG"
    assert profile.education_level == "Undergraduate"


def test_unknown_field_rejected(db_session, alice_chat) -> None:
    alice, chat = alice_chat
    with pytest.raises(ValueError, match="Unknown"):
        svc.upsert_learner_profile(db_session, alice, chat.id, {"password": "nope"})


def test_other_user_cannot_touch_profile(db_session, alice_chat, make_user) -> None:
    _, chat = alice_chat
    bob = make_user()
    with pytest.raises(NotFoundError):
        svc.upsert_learner_profile(db_session, bob, chat.id, {"topic": "hijack"})


def test_confirm_requires_topic(db_session, alice_chat) -> None:
    alice, chat = alice_chat
    svc.upsert_learner_profile(db_session, alice, chat.id, {"education_level": "School"})
    with pytest.raises(InvalidOperationError):
        svc.confirm_learner_profile(db_session, alice, chat.id)


def test_changing_confirmed_profile_requires_reconfirmation(db_session, alice_chat) -> None:
    alice, chat = alice_chat
    svc.upsert_learner_profile(db_session, alice, chat.id, {"topic": "Introduction to RAG"})
    assert svc.confirm_learner_profile(db_session, alice, chat.id).is_confirmed is True

    unchanged = svc.upsert_learner_profile(db_session, alice, chat.id, {"topic": "Introduction to RAG"})
    assert unchanged.is_confirmed is True  # same value: still confirmed

    changed = svc.upsert_learner_profile(db_session, alice, chat.id, {"preferred_style": "Visual analogies"})
    assert changed.is_confirmed is False
    assert changed.confirmed_at is None
