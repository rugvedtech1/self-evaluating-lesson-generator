"""Intake Assistant (AI component 1): conversational collection of a per-chat learner profile.

Responsibilities are split deliberately:
- Python decides WHAT to ask next (so answered questions are never asked again) and owns all state.
- The LLM extracts facts from free text (and may infer very likely ones, clearly marked),
  and phrases the next question naturally.
Both LLM calls run BEFORE any database write, so an LLM failure leaves no partial state.
"""

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidOperationError
from app.intake.fields import INTAKE_FIELDS, NOT_SPECIFIED, plan_next_question
from app.intake.llm import IntakeLLM
from app.intake.prompts import INFERRED_MARKER
from app.intake.schemas import ExtractionRequest, QuestionRequest
from app.models import Chat, ChatProfile, Message
from app.services import chats as chat_service
from app.services import learner_profiles as profile_service

COLLECTING_STATUSES = ("intake", "awaiting_confirmation")
HISTORY_LIMIT = 12
MAX_VALUE_LENGTH = 300
CONFIRMED_MESSAGE = "Thank you! Your learner profile is confirmed. I'll use it to prepare your lesson."
CORRECTION_HINT = ("No problem. Tell me what you'd like to change, "
                   "or click **Confirm profile** if everything looks right.")
INFERRED_NOTE = "Items marked *(inferred)* are my best guess. Tell me if any are wrong."


class _MessageLike(Protocol):
    role: str
    kind: str
    payload: Mapping[str, Any]


# ------------------------------------------------------------------ pure helpers
def is_inferred(value: str | None) -> bool:
    return bool(value) and value.strip().lower().endswith(INFERRED_MARKER)


def asked_field_counts(messages: Sequence[_MessageLike]) -> Counter[str]:
    return Counter(
        m.payload["intake_field"] for m in messages
        if m.role == "assistant" and m.kind == "intake_question" and m.payload.get("intake_field")
    )


def last_asked_field(messages: Sequence[_MessageLike]) -> str | None:
    for message in reversed(messages):
        if message.role == "assistant":
            return message.payload.get("intake_field") if message.kind == "intake_question" else None
    return None


def clean_updates(raw: Mapping[str, Any], current: Mapping[str, str | None]) -> dict[str, str]:
    """Keep only known fields with new, non-empty, normalised values.

    An inferred value may fill an empty field, but never overwrites what the learner said.
    """
    cleaned: dict[str, str] = {}
    for name, value in raw.items():
        if name not in profile_service.PROFILE_FIELDS or value is None:
            continue
        text = " ".join(str(value).split())[:MAX_VALUE_LENGTH]
        if not text or text == current.get(name):
            continue
        if is_inferred(text) and current.get(name):
            continue
        cleaned[name] = text
    return cleaned


def build_profile_summary(profile: Mapping[str, str | None]) -> str:
    """Built from stored values only, so the summary can never invent details."""
    lines = ["Here's what I've learned about you:", ""]
    lines += [f"- **{spec.label}:** {profile.get(spec.name) or NOT_SPECIFIED}" for spec in INTAKE_FIELDS]
    if profile.get("additional_notes"):
        lines.append(f"- **Other notes:** {profile['additional_notes']}")
    lines.append("")
    if any(is_inferred(value) for value in profile.values()):
        lines += [INFERRED_NOTE, ""]
    lines.append("Does this look right? Click **Confirm profile** to continue, or tell me what to change.")
    return "\n".join(lines)


def _profile_dict(profile: ChatProfile | None) -> dict[str, str | None]:
    return {name: (getattr(profile, name) if profile else None) for name in profile_service.PROFILE_FIELDS}


# ------------------------------------------------------------------ results
@dataclass(frozen=True)
class IntakeResult:
    user_message: Message
    assistant_message: Message
    chat: Chat
    profile: ChatProfile | None


@dataclass(frozen=True)
class ConfirmationResult:
    chat: Chat
    profile: ChatProfile
    assistant_message: Message


def confirm_profile(db: Session, user_id: uuid.UUID, chat_id: uuid.UUID) -> ConfirmationResult:
    chat = chat_service.get_chat(db, user_id, chat_id)
    if chat.status != "awaiting_confirmation":
        raise InvalidOperationError("The learner profile is not ready to be confirmed yet.")
    profile = profile_service.confirm_learner_profile(db, user_id, chat_id)
    chat.status = "generating"
    message = chat_service.add_message(db, user_id, chat_id, role="assistant",
                                       kind="profile_confirmed", content=CONFIRMED_MESSAGE)
    return ConfirmationResult(chat=chat, profile=profile, assistant_message=message)


# ------------------------------------------------------------------ the assistant
class IntakeAssistant:
    def __init__(self, llm: IntakeLLM) -> None:
        self._llm = llm

    def handle_user_message(
        self, db: Session, user_id: uuid.UUID, chat_id: uuid.UUID, content: str
    ) -> IntakeResult:
        chat = chat_service.get_chat(db, user_id, chat_id)  # ownership check
        if chat.status not in COLLECTING_STATUSES:
            raise InvalidOperationError("This chat has finished collecting learner information.")

        history = chat_service.list_messages(db, user_id, chat_id)
        profile = profile_service.get_learner_profile(db, user_id, chat_id)
        current = _profile_dict(profile)
        awaiting = chat.status == "awaiting_confirmation"
        transcript = [(m.role, m.content) for m in history[-HISTORY_LIMIT:]]

        # 1) UNDERSTAND (LLM) - nothing written yet
        extraction = self._llm.extract(ExtractionRequest(
            profile=current, asked_field=last_asked_field(history), awaiting_confirmation=awaiting,
            transcript=transcript, latest_message=content,
        ))
        updates = clean_updates(extraction.updates.model_dump(), current)
        merged = {**current, **updates}

        # 2) DECIDE (Python)
        confirm_now = awaiting and extraction.confirms_profile and not updates
        plan = plan_next_question(merged, asked_field_counts(history))
        for name in plan.give_up_fields:
            if not merged.get(name):
                updates[name] = merged[name] = NOT_SPECIFIED

        reply, kind, payload, status = "", "chat", {}, chat.status
        if not confirm_now:
            if plan.next_field is not None:
                # 3) PHRASE (LLM) - still nothing written
                question = self._llm.ask(QuestionRequest(
                    field=plan.next_field, profile=merged, transcript=transcript, latest_message=content,
                ))
                reply = question or plan.next_field.fallback_question
                kind, payload, status = "intake_question", {"intake_field": plan.next_field.name}, "intake"
            elif awaiting and not updates:
                reply, kind, status = CORRECTION_HINT, "intake_hint", "awaiting_confirmation"
            else:
                reply, kind, status = build_profile_summary(merged), "profile_summary", "awaiting_confirmation"

        # 4) PERSIST - only after every LLM call has succeeded
        user_message = chat_service.add_message(db, user_id, chat_id, role="user", content=content)
        if updates:
            profile = profile_service.upsert_learner_profile(db, user_id, chat_id, updates)
        if confirm_now:
            confirmation = confirm_profile(db, user_id, chat_id)
            return IntakeResult(user_message, confirmation.assistant_message, confirmation.chat, confirmation.profile)

        chat.status = status
        assistant_message = chat_service.add_message(db, user_id, chat_id, role="assistant",
                                                     content=reply, kind=kind, payload=payload)
        return IntakeResult(user_message, assistant_message, chat, profile)
