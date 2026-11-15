"""Chat and message routes. The current user always comes from the verified token."""

import uuid

from fastapi import APIRouter, Response, status

from app.api.deps import CurrentUser, DbSession, IntakeAssistantDep
from app.intake import service as intake_service
from app.models import Chat, ChatProfile, Message
from app.schemas.chat import (
    ChatCreate, ChatDetail, ChatSummary, ChatUpdate, ConversationTurn, LearnerProfileOut,
    MessageCreate, MessageOut, ProfileConfirmation,
)
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service
from app.services.profiles import ensure_profile

router = APIRouter(prefix="/chats", tags=["chats"])


def _profile_out(profile: ChatProfile | None) -> LearnerProfileOut | None:
    return LearnerProfileOut.model_validate(profile) if profile else None


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
        learner_profile=_profile_out(profile),
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


@router.post("/{chat_id}/messages", response_model=ConversationTurn, status_code=status.HTTP_201_CREATED)
def post_message(
    chat_id: uuid.UUID, body: MessageCreate, user: CurrentUser, db: DbSession, intake: IntakeAssistantDep
) -> ConversationTurn:
    """Save the learner's message and let the Intake Assistant reply (clients only speak as 'user')."""
    result = intake.handle_user_message(db, user.id, chat_id, body.content)
    return ConversationTurn(
        user_message=MessageOut.model_validate(result.user_message),
        assistant_message=MessageOut.model_validate(result.assistant_message),
        chat=ChatSummary.model_validate(result.chat),
        learner_profile=_profile_out(result.profile),
    )


@router.post("/{chat_id}/profile/confirm", response_model=ProfileConfirmation)
def confirm_profile(chat_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ProfileConfirmation:
    result = intake_service.confirm_profile(db, user.id, chat_id)
    return ProfileConfirmation(
        chat=ChatSummary.model_validate(result.chat),
        learner_profile=LearnerProfileOut.model_validate(result.profile),
        assistant_message=MessageOut.model_validate(result.assistant_message),
    )
