"""Topic-specific teaching requirements, kept separate from the general evaluation rubric."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RequiredConcept:
    key: str
    title: str
    description: str


@dataclass(frozen=True)
class TopicConfig:
    key: str
    title: str
    aliases: tuple[str, ...]
    required_concepts: tuple[RequiredConcept, ...]
    guidance: str = ""


def normalise(text: str) -> str:
    """Lowercase, punctuation to spaces, single spaces: 'Retrieval-Augmented' -> 'retrieval augmented'."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


GENERIC_TOPIC = TopicConfig(
    key="generic",
    title="General topic",
    aliases=(),
    required_concepts=(
        RequiredConcept("definition", "What it is", "A clear, simple definition of the topic."),
        RequiredConcept("motivation", "Why it matters", "The problem it solves, or why a learner should care."),
        RequiredConcept("mechanism", "How it works", "The main steps or parts, explained in order."),
        RequiredConcept("key_concepts", "Key concepts and terms", "The essential ideas and vocabulary, each explained."),
        RequiredConcept("examples", "Practical examples", "Concrete, real-world examples and how they work."),
    ),
)
