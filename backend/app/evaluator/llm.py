"""Lesson Evaluator's AI judge (AI component 3): its LLM boundary."""

from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.evaluator.prompts import render_judge_input
from app.evaluator.schemas import JudgeRequest, LLMJudgement
from app.llm.calls import as_model, call_llm


class LessonJudge(Protocol):
    def judge(self, request: JudgeRequest) -> LLMJudgement: ...


class LangChainLessonJudge:
    def __init__(self, model: BaseChatModel) -> None:
        self._structured = model.with_structured_output(LLMJudgement, method="function_calling")

    def judge(self, request: JudgeRequest) -> LLMJudgement:
        messages = [SystemMessage(request.instructions), HumanMessage(render_judge_input(request))]
        return as_model(call_llm(lambda: self._structured.invoke(messages)), LLMJudgement)
