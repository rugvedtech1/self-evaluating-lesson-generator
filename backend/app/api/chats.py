"""Chat, message and lesson-run routes. The current user always comes from the verified token."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Response, status
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, IntakeAssistantDep, LessonRunnerDep
from app.intake import service as intake_service
from app.models import Chat, ChatProfile, Message
from app.schemas.chat import (
    ChatCreate, ChatSummary, ChatUpdate, ChatWithLesson, ConversationTurnWithRun, LearnerProfileOut,
    LessonRunDetail, LessonRunOut, LessonVersionOut, MessageCreate, MessageOut, ProfileConfirmationWithRun,
)
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service
from app.services import lessons as lesson_service
from app.services.profiles import ensure_profile
from app.workflows.runner import LessonWorkflowRunner, start_lesson_run

router = APIRouter(prefix="/chats", tags=["chats"])


def _profile_out(profile: ChatProfile | None) -> LearnerProfileOut | None:
    return LearnerProfileOut.model_validate(profile) if profile else None


def _latest_run(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> LessonRunDetail | None:
    run = lesson_service.get_latest_lesson_run(db, user_id, chat_id)
    if run is None:
        return None
    history = lesson_service.get_lesson_run_history(db, user_id, run.id)
    return LessonRunDetail(
        **LessonRunOut.model_validate(run).model_dump(),
        versions=[LessonVersionOut.model_validate(a.version) for a in history.attempts],
    )


def _start_generation(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID,
                      background: BackgroundTasks, runner: LessonWorkflowRunner) -> LessonRunOut:
    run = start_lesson_run(db, user_id, chat_id)
    db.commit()  # the background task reads this run through its own database session
    background.add_task(runner.run, run.id, user_id)
    return LessonRunOut.model_validate(run)


@router.post("", response_model=ChatSummary, status_code=status.HTTP_201_CREATED)
def create_chat(body: ChatCreate, user: CurrentUser, db: DbSession) -> Chat:
    ensure_profile(db, user.id, user.email)  # guarantees the owner row exists
    return chat_service.create_chat(db, user.id, body.title)


@router.get("", response_model=list[ChatSummary])
def list_chats(user: CurrentUser, db: DbSession) -> list[Chat]:
    return chat_service.list_chats(db, user.id)


@router.get("/{chat_id}", response_model=ChatWithLesson)
def get_chat(chat_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ChatWithLesson:
    chat = chat_service.get_chat(db, user.id, chat_id)
    messages = chat_service.list_messages(db, user.id, chat_id)
    profile = profile_service.get_learner_profile(db, user.id, chat_id)
    return ChatWithLesson(
        chat=ChatSummary.model_validate(chat),
        messages=[MessageOut.model_validate(m) for m in messages],
        learner_profile=_profile_out(profile),
        latest_run=_latest_run(db, user.id, chat_id),
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


@router.post("/{chat_id}/messages", response_model=ConversationTurnWithRun, status_code=status.HTTP_201_CREATED)
def post_message(chat_id: uuid.UUID, body: MessageCreate, user: CurrentUser, db: DbSession,
                 intake: IntakeAssistantDep, runner: LessonRunnerDep,
                 background: BackgroundTasks) -> ConversationTurnWithRun:
    """Save the learner's message; the Intake Assistant replies. Confirming in words starts generation."""
    result = intake.handle_user_message(db, user.id, chat_id, body.content)
    lesson_run = (_start_generation(db, user.id, chat_id, background, runner)
                  if result.chat.status == "generating" else None)
    return ConversationTurnWithRun(
        user_message=MessageOut.model_validate(result.user_message),
        assistant_message=MessageOut.model_validate(result.assistant_message),
        chat=ChatSummary.model_validate(result.chat),
        learner_profile=_profile_out(result.profile),
        lesson_run=lesson_run,
    )


@router.post("/{chat_id}/profile/confirm", response_model=ProfileConfirmationWithRun)
def confirm_profile(chat_id: uuid.UUID, user: CurrentUser, db: DbSession, runner: LessonRunnerDep,
                    background: BackgroundTasks) -> ProfileConfirmationWithRun:
    result = intake_service.confirm_profile(db, user.id, chat_id)
    lesson_run = _start_generation(db, user.id, chat_id, background, runner)
    return ProfileConfirmationWithRun(
        chat=ChatSummary.model_validate(result.chat),
        learner_profile=LearnerProfileOut.model_validate(result.profile),
        assistant_message=MessageOut.model_validate(result.assistant_message),
        lesson_run=lesson_run,
    )


@router.post("/{chat_id}/lesson-runs", response_model=LessonRunOut, status_code=status.HTTP_202_ACCEPTED)
def start_lesson(chat_id: uuid.UUID, user: CurrentUser, db: DbSession, runner: LessonRunnerDep,
                 background: BackgroundTasks) -> LessonRunOut:
    """Start (or, after a technical failure, retry) lesson generation. 202 = accepted, runs in background."""
    return _start_generation(db, user.id, chat_id, background, runner)
