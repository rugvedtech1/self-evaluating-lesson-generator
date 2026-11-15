"""Shared LLM call boundary: provider problems become technical errors, bad output becomes response errors."""

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, ValidationError

from app.core.exceptions import LLMResponseError, LLMUnavailableError

logger = logging.getLogger(__name__)
T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)

INVALID_RESPONSE = "The AI service returned an invalid response. Please try again."
UNAVAILABLE = "The AI service is temporarily unavailable. Please try again."


def _details(exc: Exception) -> dict[str, str]:
    # Type + a short excerpt of the message: enough to diagnose, never the whole prompt.
    return {"error_type": type(exc).__name__, "error": " ".join(str(exc).split())[:600]}


def call_llm(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except (ValidationError, OutputParserException) as exc:
        logger.warning("LLM returned invalid output", extra={"context": _details(exc)})
        raise LLMResponseError(INVALID_RESPONSE) from exc
    except Exception as exc:  # provider / network / quota / timeout: a technical failure
        logger.warning("LLM call failed", extra={"context": _details(exc)})
        raise LLMUnavailableError(UNAVAILABLE) from exc


def as_model(result: Any, model_cls: type[M]) -> M:
    """Accept a parsed model or a dict; anything else (or invalid data) is a response error."""
    if isinstance(result, model_cls):
        return result
    if isinstance(result, dict):
        return call_llm(lambda: model_cls.model_validate(result))
    raise LLMResponseError(INVALID_RESPONSE)


def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # content blocks
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return ""
