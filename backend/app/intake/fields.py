"""What the Intake Assistant collects, and the deterministic rule for what to ask next."""

from collections.abc import Mapping
from dataclasses import dataclass

NOT_SPECIFIED = "Not specified"
MAX_ASKS_PER_FIELD = 2


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    purpose: str
    examples: str
    fallback_question: str
    can_skip: bool = True


INTAKE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("topic", "Topic", "the subject the learner wants to learn",
              "Introduction to RAG; Python basics; how vaccines work",
              "What topic would you like to learn about?", can_skip=False),
    FieldSpec("education_level", "Education level", "their education level or current studies",
              "high school; second-year commerce student; working professional",
              "What is your current education level?"),
    FieldSpec("english_proficiency", "English level", "how comfortable they are reading English",
              "basic; intermediate; fluent",
              "How comfortable are you reading English: basic, intermediate or fluent?"),
    FieldSpec("technical_background", "Technical background", "their programming or technical experience",
              "none; a little Python; professional software developer",
              "Do you have any programming or technical experience?"),
    FieldSpec("ai_knowledge", "AI knowledge", "what they already know about AI and large language models",
              "never used ChatGPT; use ChatGPT daily; have trained ML models",
              "What do you already know about AI tools like ChatGPT?"),
    FieldSpec("preferred_style", "Explanation style", "how they like things to be explained",
              "real-life analogies; step-by-step; lots of examples; short and direct",
              "How do you like things explained: analogies, step-by-step, or lots of examples?"),
)
FIELDS_BY_NAME = {spec.name: spec for spec in INTAKE_FIELDS}


@dataclass(frozen=True)
class QuestionPlan:
    next_field: FieldSpec | None          # None = profile complete
    give_up_fields: tuple[str, ...] = ()  # asked too often without an answer -> "Not specified"


def plan_next_question(
    profile: Mapping[str, str | None],
    asked_counts: Mapping[str, int],
    max_asks: int = MAX_ASKS_PER_FIELD,
) -> QuestionPlan:
    """First empty field, in a fixed order. Filled fields are never asked again."""
    give_up: list[str] = []
    for spec in INTAKE_FIELDS:
        if profile.get(spec.name):
            continue
        if spec.can_skip and asked_counts.get(spec.name, 0) >= max_asks:
            give_up.append(spec.name)
            continue
        return QuestionPlan(next_field=spec, give_up_fields=tuple(give_up))
    return QuestionPlan(next_field=None, give_up_fields=tuple(give_up))
