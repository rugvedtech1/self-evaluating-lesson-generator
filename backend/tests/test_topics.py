"""Topic configuration: alias matching and the mandatory RAG concepts."""

import pytest

from app.topics.base import GENERIC_TOPIC
from app.topics.intro_to_rag import INTRO_TO_RAG
from app.topics.registry import get_topic, match_topic


@pytest.mark.parametrize("topic", [
    "Introduction to RAG", "RAG", "rag basics", "Retrieval-Augmented Generation",
    "intro to retrieval augmented generation (RAG)",
])
def test_rag_aliases_match(topic: str) -> None:
    assert match_topic(topic).key == "intro_to_rag"


@pytest.mark.parametrize("topic", ["Drag and drop in HTML", "Data storage", "Python basics", "", None])
def test_other_topics_use_generic_requirements(topic) -> None:
    assert match_topic(topic).key == "generic"


def test_rag_config_has_the_eight_mandatory_concepts() -> None:
    titles = [c.title for c in INTRO_TO_RAG.required_concepts]
    assert len(titles) == 8
    assert titles[0] == "What RAG is"
    assert "Benefits and limitations of RAG" in titles


def test_concept_keys_are_unique() -> None:
    for config in (INTRO_TO_RAG, GENERIC_TOPIC):
        keys = [c.key for c in config.required_concepts]
        assert len(keys) == len(set(keys))


def test_get_topic_falls_back_to_generic() -> None:
    assert get_topic("intro_to_rag") is INTRO_TO_RAG
    assert get_topic("no-such-topic") is GENERIC_TOPIC
    assert get_topic(None) is GENERIC_TOPIC
