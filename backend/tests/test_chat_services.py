"""Chats & messages services: ownership, ordering, titles, cascades."""

import pytest
from sqlalchemy import func, select

from app.core.exceptions import NotFoundError
from app.models import Chat, Message
from app.services import chats as svc

pytestmark = pytest.mark.db


def test_list_chats_returns_only_own_chats(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    svc.create_chat(db_session, alice, "Alice 1")
    svc.create_chat(db_session, bob, "Bob 1")
    assert [c.title for c in svc.list_chats(db_session, alice)] == ["Alice 1"]


def test_get_other_users_chat_is_not_found(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    bobs_chat = svc.create_chat(db_session, bob)
    with pytest.raises(NotFoundError):
        svc.get_chat(db_session, alice, bobs_chat.id)


def test_rename_respects_ownership(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    chat = svc.create_chat(db_session, alice)
    with pytest.raises(NotFoundError):
        svc.rename_chat(db_session, bob, chat.id, "hijacked")
    assert svc.rename_chat(db_session, alice, chat.id, "Renamed").title == "Renamed"


def test_delete_own_chat_cascades_and_others_cannot_delete(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    chat = svc.create_chat(db_session, alice)
    svc.add_message(db_session, alice, chat.id, role="user", content="hello")

    with pytest.raises(NotFoundError):
        svc.delete_chat(db_session, bob, chat.id)

    svc.delete_chat(db_session, alice, chat.id)
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(Chat).where(Chat.id == chat.id)) == 0
    assert db_session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == chat.id)) == 0


def test_cannot_add_message_to_other_users_chat(db_session, make_user) -> None:
    alice, bob = make_user(), make_user()
    bobs_chat = svc.create_chat(db_session, bob)
    with pytest.raises(NotFoundError):
        svc.add_message(db_session, alice, bobs_chat.id, role="user", content="sneaky")
    count = db_session.scalar(select(func.count()).select_from(Message).where(Message.chat_id == bobs_chat.id))
    assert count == 0


def test_first_user_message_sets_title_once(db_session, make_user) -> None:
    alice = make_user()
    chat = svc.create_chat(db_session, alice)
    svc.add_message(db_session, alice, chat.id, role="user", content="I want to learn Introduction to RAG")
    svc.add_message(db_session, alice, chat.id, role="user", content="Something else entirely")
    assert svc.get_chat(db_session, alice, chat.id).title == "I want to learn Introduction to RAG"


def test_messages_returned_in_creation_order(db_session, make_user) -> None:
    alice = make_user()
    chat = svc.create_chat(db_session, alice)
    for i, role in enumerate(["user", "assistant", "user"]):
        svc.add_message(db_session, alice, chat.id, role=role, content=f"m{i}")
    assert [m.content for m in svc.list_messages(db_session, alice, chat.id)] == ["m0", "m1", "m2"]


def test_new_message_moves_chat_to_top_of_recent_list(db_session, make_user) -> None:
    alice = make_user()
    older = svc.create_chat(db_session, alice, "Older")
    svc.create_chat(db_session, alice, "Newer")
    svc.add_message(db_session, alice, older.id, role="user", content="bump")
    db_session.expire_all()
    assert svc.list_chats(db_session, alice)[0].title == "Older"
