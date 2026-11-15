"""Builds LangChain chat models from settings: switching provider/model is a .env change."""

from typing import Any, Literal

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMConfigurationError

Component = Literal["intake", "generator", "evaluator"]
SUPPORTED_PROVIDERS = ("openai",)


def model_name_for(component: Component, settings: Settings) -> str:
    return {
        "intake": settings.intake_model,
        "generator": settings.generator_model,
        "evaluator": settings.evaluator_model,
    }[component]


def build_chat_model(
    component: Component,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
) -> BaseChatModel:
    settings = settings or get_settings()
    provider = settings.llm_provider
    if provider not in SUPPORTED_PROVIDERS:
        raise LLMConfigurationError(
            f"Unsupported LLM_PROVIDER '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}."
        )
    if settings.openai_api_key is None:
        raise LLMConfigurationError("OPENAI_API_KEY is not set. Add it to your .env file.")

    kwargs: dict[str, Any] = {
        "api_key": settings.openai_api_key.get_secret_value(),
        "timeout": settings.llm_timeout_seconds,
        "max_retries": settings.llm_max_retries,  # short, bounded retries for transient errors
    }
    if temperature is not None:
        kwargs["temperature"] = temperature
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return init_chat_model(model_name_for(component, settings), model_provider=provider, **kwargs)
