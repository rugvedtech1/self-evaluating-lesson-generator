"""Lesson Generator (AI component 2): its LLM boundary."""

from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.generator.prompts import render_generation_input
from app.generator.schemas import GenerationRequest, LessonDraft
from app.llm.calls import as_model, call_llm


class LessonGenerator(Protocol):
    def generate(self, request: GenerationRequest) -> LessonDraft: ...


class LangChainLessonGenerator:
    def __init__(self, model: BaseChatModel) -> None:
        self._structured = model.with_structured_output(LessonDraft, method="function_calling")

    def generate(self, request: GenerationRequest) -> LessonDraft:
        messages = [
            SystemMessage(request.instructions),  # versioned instructions from prompt_versions
            HumanMessage(render_generation_input(request)),
        ]
        return as_model(call_llm(lambda: self._structured.invoke(messages)), LessonDraft)
