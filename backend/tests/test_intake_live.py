"""OPTIONAL live test against the real LLM. Costs a fraction of a cent; skipped by default.

Run with:  RUN_LIVE_LLM_TESTS=1 pytest -m live -v
"""

import os

import pytest

from app.intake.fields import FIELDS_BY_NAME
from app.intake.llm import LangChainIntakeLLM
from app.intake.schemas import ExtractionRequest, QuestionRequest
from app.llm.factory import build_chat_model
from app.services.learner_profiles import PROFILE_FIELDS

pytestmark = pytest.mark.live
MESSAGE = "Hi! I want to learn Introduction to RAG. I'm a second-year computer science student."


@pytest.fixture
def live_llm() -> LangChainIntakeLLM:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to call the real LLM (costs a tiny amount).")
    return LangChainIntakeLLM(build_chat_model("intake", temperature=0))


def test_real_llm_extracts_facts_and_asks_one_question(live_llm: LangChainIntakeLLM) -> None:
    extraction = live_llm.extract(ExtractionRequest(
        profile={name: None for name in PROFILE_FIELDS}, asked_field=None,
        awaiting_confirmation=False, transcript=[], latest_message=MESSAGE,
    ))
    assert extraction.updates.topic and "rag" in extraction.updates.topic.lower()
    assert extraction.updates.education_level

    question = live_llm.ask(QuestionRequest(
        field=FIELDS_BY_NAME["preferred_style"],
        profile={"topic": extraction.updates.topic, "education_level": extraction.updates.education_level},
        transcript=[("user", MESSAGE)], latest_message=MESSAGE,
    ))
    print("\nLIVE QUESTION:", question)
    assert "?" in question
