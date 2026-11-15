"""Lesson Generator input and validated output."""

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.topics.base import TopicConfig


class LessonDraft(BaseModel):
    title: str = Field(min_length=3, max_length=200, description="The lesson title.")
    lesson_markdown: str = Field(
        min_length=200,
        description="The complete lesson in Markdown, starting with a single '# ' title line, using '## ' sections.",
    )
    change_summary: str | None = Field(
        None, max_length=1500,
        description="Only when revising: what changed compared with the previous version and why. Null otherwise.",
    )


@dataclass(frozen=True)
class GenerationRequest:
    topic: str
    topic_config: TopicConfig
    learner_profile: Mapping[str, str | None]
    instructions: str                      # the versioned, evolvable system prompt
    previous_lesson: str | None = None     # Step 6: regeneration
    feedback: str | None = None            # Step 6: evaluator feedback to fix
