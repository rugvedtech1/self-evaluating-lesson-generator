"""Chats and messages. Every function is scoped to the verified `user_id`."""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models import Chat, Message

DEFAULT_TITLE = "New chat"
AUTO_TITLE_LENGTH = 60


def _title_from(content: str) -> str:
    first_line = " ".join(content.strip().splitlines()[0].split()) if content.strip() else DEFAULT_TITLE
    return first_line if len(first_line) <= AUTO_TITLE_LENGTH else first_line[: AUTO_TITLE_LENGTH - 1] + "…"


def create_chat(db: Session, user_id: uuid.UUID, title: str | None = None) -> Chat:
    chat = Chat(user_id=user_id, title=title or DEFAULT_TITLE)
    db.add(chat)
    db.flush()
    return chat


def list_chats(db: Session, user_id: uuid.UUID, limit: int = 50) -> list[Chat]:
    stmt = (
        select(Chat)
        .where(Chat.user_id == user_id)
        .order_by(Chat.updated_at.desc(), Chat.created_at.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt))


def get_chat(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> Chat:
    """Ownership check lives in the WHERE clause: another user's chat is simply 'not found'."""
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
    if chat is None:
        raise NotFoundError("Chat not found.")
    return chat


def rename_chat(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID, title: str) -> Chat:
    chat = get_chat(db, user_id, chat_id)
    chat.title = title
    db.flush()
    return chat


def delete_chat(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> None:
    chat = get_chat(db, user_id, chat_id)
    db.delete(chat)  # messages, learner profile, lesson runs... removed by ON DELETE CASCADE
    db.flush()


def add_message(
    db: Session,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    *,
    role: str,
    content: str,
    kind: str = "chat",
    payload: dict[str, Any] | None = None,
) -> Message:
    chat = get_chat(db, user_id, chat_id)
    message = Message(chat_id=chat.id, user_id=user_id, role=role, kind=kind,
                      content=content, payload=payload or {})
    db.add(message)
    if role == "user" and chat.title == DEFAULT_TITLE:
        chat.title = _title_from(content)
    # clock_timestamp(): moves this chat to the top of "recent chats" even within one transaction.
    chat.updated_at = func.clock_timestamp()
    db.flush()
    return message


def list_messages(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> list[Message]:
    get_chat(db, user_id, chat_id)  # ownership check first
    stmt = (
        select(Message)
        .where(Message.chat_id == chat_id, Message.user_id == user_id)
        .order_by(Message.created_at, Message.id)
    )
    return list(db.scalars(stmt))
