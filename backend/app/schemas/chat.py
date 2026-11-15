"""Request/response models for chats, messages and learner profiles."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=80)


class ChatUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=80)


class ChatSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class MessageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=8000)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    kind: str
    content: str
    payload: dict[str, Any]
    created_at: datetime


class LearnerProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    topic: str | None
    education_level: str | None
    english_proficiency: str | None
    technical_background: str | None
    ai_knowledge: str | None
    preferred_style: str | None
    additional_notes: str | None
    is_confirmed: bool
    confirmed_at: datetime | None


class ChatDetail(BaseModel):
    chat: ChatSummary
    messages: list[MessageOut]
    learner_profile: LearnerProfileOut | None


class ConversationTurn(BaseModel):
    """Result of sending one message: what was saved and how the chat changed."""

    user_message: MessageOut
    assistant_message: MessageOut
    chat: ChatSummary
    learner_profile: LearnerProfileOut | None


class ProfileConfirmation(BaseModel):
    chat: ChatSummary
    learner_profile: LearnerProfileOut
    assistant_message: MessageOut
