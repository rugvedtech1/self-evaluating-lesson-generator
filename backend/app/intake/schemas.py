"""Validated LLM output (Pydantic) and the inputs we give to the LLM."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.intake.fields import FieldSpec

_SHORT = ("Short value (under 15 words) in the learner's own words. "
          "End with ' (inferred)' if not stated but very likely. Null if unknown.")


class ProfileUpdates(BaseModel):
    topic: str | None = Field(None, description="Subject the learner wants to learn. " + _SHORT)
    education_level: str | None = Field(None, description="Education level or current studies. " + _SHORT)
    english_proficiency: str | None = Field(None, description="Comfort reading English. " + _SHORT)
    technical_background: str | None = Field(None, description="Programming/technical experience. " + _SHORT)
    ai_knowledge: str | None = Field(None, description="Existing knowledge of AI / LLMs. " + _SHORT)
    preferred_style: str | None = Field(None, description="Preferred explanation style. " + _SHORT)
    additional_notes: str | None = Field(None, description="Any other useful learning preference. " + _SHORT)


class ProfileExtraction(BaseModel):
    """What the extraction LLM call must return for each learner message."""

    updates: ProfileUpdates = Field(default_factory=ProfileUpdates)
    confirms_profile: bool = Field(
        False, description="True ONLY if a profile summary was shown and the learner clearly says it is correct."
    )


@dataclass(frozen=True)
class ExtractionRequest:
    profile: Mapping[str, str | None]
    asked_field: str | None
    awaiting_confirmation: bool
    transcript: Sequence[tuple[str, str]]
    latest_message: str


@dataclass(frozen=True)
class QuestionRequest:
    field: FieldSpec
    profile: Mapping[str, str | None]
    transcript: Sequence[tuple[str, str]]
    latest_message: str
