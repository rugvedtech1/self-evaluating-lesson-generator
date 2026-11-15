"""Maps a learner's free-text topic to a topic configuration (generic if no specific one exists)."""

from app.topics.base import GENERIC_TOPIC, TopicConfig, normalise
from app.topics.intro_to_rag import INTRO_TO_RAG

TOPICS: tuple[TopicConfig, ...] = (INTRO_TO_RAG,)
_BY_KEY = {config.key: config for config in (*TOPICS, GENERIC_TOPIC)}


def match_topic(topic: str | None) -> TopicConfig:
    """Whole-word alias match: 'rag' matches 'Intro to RAG' but not 'drag and drop'."""
    text = f" {normalise(topic or '')} "
    for config in TOPICS:
        if any(f" {normalise(alias)} " in text for alias in config.aliases):
            return config
    return GENERIC_TOPIC


def get_topic(key: str | None) -> TopicConfig:
    return _BY_KEY.get(key or "", GENERIC_TOPIC)
