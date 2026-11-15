"""Demo mode replaces only the chosen Generator attempts, with an honestly labelled dataset lesson."""

import pytest

from app.core.config import get_settings
from app.evaluator.dataset import CASES
from app.generator.schemas import GenerationRequest, LessonDraft
from app.topics.base import GENERIC_TOPIC
from app.topics.registry import get_topic
from app.workflows.demo import BANNER, DemoFlawGenerator

JARGON = next(c for c in CASES if c.key == "unexplained_jargon")


class RealGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return LessonDraft(title="Real", lesson_markdown="# Real\n\n" + "A real lesson sentence. " * 60,
                           change_summary="real")


def req(previous: str | None = None, topic_config=None) -> GenerationRequest:
    return GenerationRequest(topic="Introduction to RAG", topic_config=topic_config or get_topic("intro_to_rag"),
                             learner_profile={}, instructions="X", previous_lesson=previous,
                             feedback="fix it" if previous else None)


def test_off_is_the_default_in_tests() -> None:
    assert get_settings().demo_flaw_mode == "off"


def test_off_always_uses_the_real_generator() -> None:
    real = RealGenerator()
    assert DemoFlawGenerator(real).generate(req()).title == "Real"
    assert real.calls == 1


def test_first_replaces_attempt_one_with_labelled_dataset_lesson() -> None:
    real = RealGenerator()
    draft = DemoFlawGenerator(real, mode="first").generate(req())
    assert real.calls == 0
    assert draft.lesson_markdown.startswith("# ") and BANNER in draft.lesson_markdown
    assert draft.lesson_markdown.replace(f"\n{BANNER}\n", "", 1) == JARGON.lesson_markdown


def test_first_uses_the_real_generator_for_revisions() -> None:
    real = RealGenerator()
    assert DemoFlawGenerator(real, mode="first").generate(req(previous="old")).title == "Real"
    assert real.calls == 1


def test_all_replaces_revisions_too() -> None:
    real = RealGenerator()
    assert BANNER in DemoFlawGenerator(real, mode="all").generate(req(previous="old")).lesson_markdown
    assert real.calls == 0


def test_other_topics_are_never_replaced() -> None:
    real = RealGenerator()
    assert DemoFlawGenerator(real, mode="all").generate(req(topic_config=GENERIC_TOPIC)).title == "Real"


def test_banner_does_not_reveal_the_flaw() -> None:
    assert "jargon" not in BANNER.lower()


@pytest.mark.parametrize("mode, case", [("sometimes", "unexplained_jargon"), ("first", "nope"), ("first", "good")])
def test_invalid_configuration_fails_loudly(mode: str, case: str) -> None:
    with pytest.raises(ValueError):
        DemoFlawGenerator(RealGenerator(), mode=mode, case_key=case)
