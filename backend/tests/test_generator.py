"""Lesson Generator: input assembly, structured output validation, error mapping (no network)."""

import pytest

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.generator.llm import LangChainLessonGenerator
from app.generator.prompts import render_generation_input
from app.generator.schemas import GenerationRequest, LessonDraft
from app.topics.intro_to_rag import INTRO_TO_RAG

PROFILE = {"topic": "Introduction to RAG", "education_level": "8th standard",
           "technical_background": "None (inferred)", "preferred_style": "Step-by-step",
           "english_proficiency": None}
VALID_MARKDOWN = "# RAG for beginners\n\n" + "Short, simple sentences explain each idea. " * 10


def _request(**kwargs) -> GenerationRequest:
    return GenerationRequest(topic="Introduction to RAG", topic_config=INTRO_TO_RAG,
                             learner_profile=kwargs.pop("profile", PROFILE), instructions="INSTRUCTIONS", **kwargs)


class _Runnable:
    def __init__(self, owner) -> None:
        self.owner = owner

    def invoke(self, messages):
        self.owner.messages = messages
        if self.owner.error is not None:
            raise self.owner.error
        return self.owner.result


class StubModel:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.messages, self.kwargs = result, error, None, {}

    def with_structured_output(self, schema, **kwargs):
        self.kwargs = kwargs
        return _Runnable(self)


def test_input_includes_profile_and_every_required_concept() -> None:
    text = render_generation_input(_request())
    assert "8th standard" in text and "Step-by-step" in text and "(inferred)" in text
    assert "English level" not in text  # empty fields are left out
    for concept in INTRO_TO_RAG.required_concepts:
        assert concept.title in text
    assert "first version" in text


def test_input_for_revision_includes_previous_version_and_feedback() -> None:
    text = render_generation_input(_request(previous_lesson="OLD LESSON", feedback="Explain 'embedding'."))
    assert "OLD LESSON" in text and "Explain 'embedding'." in text and "change_summary" in text


def test_empty_profile_means_complete_beginner() -> None:
    assert "complete beginner" in render_generation_input(_request(profile={}))


def test_generator_returns_validated_draft_using_function_calling() -> None:
    draft = LessonDraft(title="RAG for beginners", lesson_markdown=VALID_MARKDOWN)
    stub = StubModel(result=draft)
    assert LangChainLessonGenerator(stub).generate(_request()) == draft
    assert stub.kwargs == {"method": "function_calling"}


def test_versioned_instructions_are_the_system_message() -> None:
    stub = StubModel(result=LessonDraft(title="RAG", lesson_markdown=VALID_MARKDOWN))
    LangChainLessonGenerator(stub).generate(_request())
    assert stub.messages[0].content == "INSTRUCTIONS"
    assert "Required concepts" in stub.messages[1].content


def test_dict_output_is_validated() -> None:
    stub = StubModel(result={"title": "RAG", "lesson_markdown": VALID_MARKDOWN})
    assert LangChainLessonGenerator(stub).generate(_request()).title == "RAG"


def test_too_short_lesson_is_a_response_error() -> None:
    stub = StubModel(result={"title": "RAG", "lesson_markdown": "tiny"})
    with pytest.raises(LLMResponseError):
        LangChainLessonGenerator(stub).generate(_request())


def test_provider_failure_is_unavailable() -> None:
    with pytest.raises(LLMUnavailableError):
        LangChainLessonGenerator(StubModel(error=RuntimeError("quota exceeded"))).generate(_request())
