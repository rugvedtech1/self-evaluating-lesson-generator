"""Responses for system-wide learning data (contains no user data)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PromptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    component: str
    version: int
    status: str
    content: str
    change_reason: str | None
    parent_version_id: uuid.UUID | None
    validation_report: dict[str, Any] | None
    created_at: datetime
    activated_at: datetime | None


class FailurePatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    criterion: str
    pattern_key: str
    description: str
    occurrence_count: int
    status: str
    first_seen_at: datetime
    last_seen_at: datetime


class EvolutionStarted(BaseModel):
    status: str
    message: str


class RollbackRequest(BaseModel):
    to_version: int | None = None
