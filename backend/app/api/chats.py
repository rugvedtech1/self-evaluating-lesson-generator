"""Chat and message routes. The current user always comes from the verified token."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession
from app.models import Chat, Message
from app.schemas.chat import (
    ChatCreate, ChatDetail, ChatSummary, ChatUpdate, LearnerProfileOut, MessageCreate, MessageOut,
)
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service
from app.services.profiles import ensure_profile

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", response_model=ChatSummary, status_code=status.HTTP_201_CREATED)
def create_chat(body: ChatCreate, user: CurrentUser, db: DbSession) -> Chat:
    ensure_profile(db, user.id, user.email)  # guarantees the owner row exists
    return chat_service.create_chat(db, user.id, body.title)


@router.get("", response_model=list[ChatSummary])
def list_chats(user: CurrentUser, db: DbSession) -> list[Chat]:
    return chat_service.list_chats(db, user.id)


@router.get("/{chat_id}", response_model=ChatDetail)
def get_chat(chat_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ChatDetail:
    chat = chat_service.get_chat(db, user.id, chat_id)
    messages = chat_service.list_messages(db, user.id, chat_id)
    profile = profile_service.get_learner_profile(db, user.id, chat_id)
    return ChatDetail(
        chat=ChatSummary.model_validate(chat),
        messages=[MessageOut.model_validate(m) for m in messages],
        learner_profile=LearnerProfileOut.model_validate(profile) if profile else None,
    )


@router.patch("/{chat_id}", response_model=ChatSummary)
def rename_chat(chat_id: uuid.UUID, body: ChatUpdate, user: CurrentUser, db: DbSession) -> Chat:
    return chat_service.rename_chat(db, user.id, chat_id, body.title)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    chat_service.delete_chat(db, user.id, chat_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{chat_id}/messages", response_model=list[MessageOut])
def list_messages(chat_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[Message]:
    return chat_service.list_messages(db, user.id, chat_id)


@router.post("/{chat_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def post_message(chat_id: uuid.UUID, body: MessageCreate, user: CurrentUser, db: DbSession) -> Message:
    # Clients may only speak as "user"; assistant messages come from our AI components.
    return chat_service.add_message(db, user.id, chat_id, role="user", content=body.content)
