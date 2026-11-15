"""LLM boundary: structured output parsing and mapping provider problems to technical errors."""

import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage

from app.core.config import Settings
from app.core.exceptions import LLMConfigurationError, LLMResponseError, LLMUnavailableError
from app.intake.fields import FIELDS_BY_NAME
from app.intake.llm import LangChainIntakeLLM
from app.intake.schemas import ExtractionRequest, ProfileExtraction, ProfileUpdates, QuestionRequest
from app.llm.factory import build_chat_model

EXTRACTION = ExtractionRequest(profile={}, asked_field=None, awaiting_confirmation=False,
                               transcript=[("user", "hi")], latest_message="I want to learn RAG")
QUESTION = QuestionRequest(field=FIELDS_BY_NAME["education_level"], profile={"topic": "RAG"},
                           transcript=[], latest_message="I want to learn RAG")


class _StubRunnable:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error = result, error

    def invoke(self, _messages):
        if self.error is not None:
            raise self.error
        return self.result


class StubChatModel:
    """Duck-typed stand-in for a LangChain chat model (no network)."""

    def __init__(self, *, structured=None, structured_error=None, content="", text_error=None) -> None:
        self.structured, self.structured_error = structured, structured_error
        self.content, self.text_error = content, text_error
        self.structured_kwargs: dict = {}

    def with_structured_output(self, schema, **kwargs):
        self.structured_kwargs = kwargs
        return _StubRunnable(self.structured, self.structured_error)

    def invoke(self, _messages):
        if self.text_error is not None:
            raise self.text_error
        return AIMessage(content=self.content)


def test_extract_returns_validated_model_using_function_calling() -> None:
    expected = ProfileExtraction(updates=ProfileUpdates(topic="RAG"))
    stub = StubChatModel(structured=expected)
    assert LangChainIntakeLLM(stub).extract(EXTRACTION) == expected
    assert stub.structured_kwargs == {"method": "function_calling"}


def test_extract_validates_dict_output() -> None:
    llm = LangChainIntakeLLM(StubChatModel(structured={"updates": {"topic": "RAG"}, "confirms_profile": False}))
    assert llm.extract(EXTRACTION).updates.topic == "RAG"


def test_extract_invalid_output_is_response_error() -> None:
    llm = LangChainIntakeLLM(StubChatModel(structured={"updates": {"topic": 123}}))
    with pytest.raises(LLMResponseError):
        llm.extract(EXTRACTION)


def test_extract_parser_failure_is_response_error() -> None:
    llm = LangChainIntakeLLM(StubChatModel(structured_error=OutputParserException("bad json")))
    with pytest.raises(LLMResponseError):
        llm.extract(EXTRACTION)


def test_provider_failure_is_unavailable_not_a_content_verdict() -> None:
    llm = LangChainIntakeLLM(StubChatModel(structured_error=RuntimeError("connection reset")))
    with pytest.raises(LLMUnavailableError):
        llm.extract(EXTRACTION)


def test_ask_returns_stripped_text() -> None:
    llm = LangChainIntakeLLM(StubChatModel(content="  What is your education level?  "))
    assert llm.ask(QUESTION) == "What is your education level?"


def test_ask_handles_content_blocks() -> None:
    llm = LangChainIntakeLLM(StubChatModel(content=[{"type": "text", "text": "Which level?"}]))
    assert llm.ask(QUESTION) == "Which level?"


def test_ask_provider_failure_is_unavailable() -> None:
    llm = LangChainIntakeLLM(StubChatModel(text_error=TimeoutError("slow")))
    with pytest.raises(LLMUnavailableError):
        llm.ask(QUESTION)


def test_missing_api_key_is_configuration_error() -> None:
    with pytest.raises(LLMConfigurationError, match="OPENAI_API_KEY"):
        build_chat_model("intake", settings=Settings(_env_file=None, openai_api_key=None))


def test_unsupported_provider_is_configuration_error() -> None:
    settings = Settings(_env_file=None, llm_provider="nope", openai_api_key="sk-test")
    with pytest.raises(LLMConfigurationError, match="Unsupported"):
        build_chat_model("intake", settings=settings)


def test_factory_uses_model_configured_for_component() -> None:
    settings = Settings(_env_file=None, openai_api_key="sk-test", intake_model="gpt-4o-mini")
    model = build_chat_model("intake", settings=settings)  # constructing makes no network call
    assert model.model_name == "gpt-4o-mini"
