"""The Intake Assistant's LLM boundary. Everything provider-specific stops here."""

import logging
from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.core.exceptions import LLMResponseError, LLMUnavailableError
from app.intake.prompts import (
    EXTRACTION_SYSTEM_PROMPT, QUESTION_SYSTEM_PROMPT, render_extraction_input, render_question_input,
)
from app.intake.schemas import ExtractionRequest, ProfileExtraction, QuestionRequest

logger = logging.getLogger(__name__)
T = TypeVar("T")


class IntakeLLM(Protocol):
    """Anything that can do the two language tasks (the real LLM, or a fake in tests)."""

    def extract(self, request: ExtractionRequest) -> ProfileExtraction: ...

    def ask(self, request: QuestionRequest) -> str: ...


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""


class LangChainIntakeLLM:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model
        # function_calling: widely supported, tolerant of optional fields in the schema.
        self._extractor = model.with_structured_output(ProfileExtraction, method="function_calling")

    @staticmethod
    def _call(fn: Callable[[], T]) -> T:
        try:
            return fn()
        except (ValidationError, OutputParserException) as exc:
            logger.warning("LLM returned invalid output", extra={"context": {"error_type": type(exc).__name__}})
            raise LLMResponseError("The assistant returned an invalid response. Please try again.") from exc
        except Exception as exc:  # provider/network/quota errors: a technical failure
            logger.warning("LLM call failed", extra={"context": {"error_type": type(exc).__name__}})
            raise LLMUnavailableError("The assistant is temporarily unavailable. Please try again.") from exc

    def extract(self, request: ExtractionRequest) -> ProfileExtraction:
        messages = [SystemMessage(EXTRACTION_SYSTEM_PROMPT), HumanMessage(render_extraction_input(request))]
        result = self._call(lambda: self._extractor.invoke(messages))
        if isinstance(result, dict):
            result = self._call(lambda: ProfileExtraction.model_validate(result))
        if not isinstance(result, ProfileExtraction):
            raise LLMResponseError("The assistant returned an invalid response. Please try again.")
        return result

    def ask(self, request: QuestionRequest) -> str:
        messages = [SystemMessage(QUESTION_SYSTEM_PROMPT), HumanMessage(render_question_input(request))]
        response = self._call(lambda: self._model.invoke(messages))
        return _text_of(response.content).strip()
