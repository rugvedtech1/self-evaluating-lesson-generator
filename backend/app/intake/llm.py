"""The Intake Assistant's LLM boundary. Everything provider-specific stops here."""

from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.intake.prompts import (
    EXTRACTION_SYSTEM_PROMPT, QUESTION_SYSTEM_PROMPT, render_extraction_input, render_question_input,
)
from app.intake.schemas import ExtractionRequest, ProfileExtraction, QuestionRequest
from app.llm.calls import as_model, call_llm, text_of


class IntakeLLM(Protocol):
    """Anything that can do the two language tasks (the real LLM, or a fake in tests)."""

    def extract(self, request: ExtractionRequest) -> ProfileExtraction: ...

    def ask(self, request: QuestionRequest) -> str: ...


class LangChainIntakeLLM:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model
        # function_calling: widely supported, tolerant of optional fields in the schema.
        self._extractor = model.with_structured_output(ProfileExtraction, method="function_calling")

    def extract(self, request: ExtractionRequest) -> ProfileExtraction:
        messages = [SystemMessage(EXTRACTION_SYSTEM_PROMPT), HumanMessage(render_extraction_input(request))]
        return as_model(call_llm(lambda: self._extractor.invoke(messages)), ProfileExtraction)

    def ask(self, request: QuestionRequest) -> str:
        messages = [SystemMessage(QUESTION_SYSTEM_PROMPT), HumanMessage(render_question_input(request))]
        response = call_llm(lambda: self._model.invoke(messages))
        return text_of(response.content).strip()
