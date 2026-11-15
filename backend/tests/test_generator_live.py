"""OPTIONAL live test: generate one real RAG lesson (about $0.01 or less). Skipped by default.

Run with:  RUN_LIVE_LLM_TESTS=1 pytest -m live -v -s
The full lesson is written to /tmp/lesson_preview.md so you can read it.
"""

import os
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.generator.llm import LangChainLessonGenerator
from app.generator.prompts import DEFAULT_GENERATOR_INSTRUCTIONS
from app.generator.schemas import GenerationRequest
from app.llm.factory import build_chat_model
from app.topics.intro_to_rag import INTRO_TO_RAG

pytestmark = pytest.mark.live


def test_real_generator_writes_a_complete_rag_lesson() -> None:
    if os.environ.get("RUN_LIVE_LLM_TESTS") != "1":
        pytest.skip("Set RUN_LIVE_LLM_TESTS=1 to call the real LLM (costs a tiny amount).")
    generator = LangChainLessonGenerator(
        build_chat_model("generator", temperature=0.4, max_tokens=get_settings().generator_max_tokens)
    )
    draft = generator.generate(GenerationRequest(
        topic="Introduction to RAG", topic_config=INTRO_TO_RAG,
        learner_profile={"education_level": "8th standard", "english_proficiency": "A little",
                         "technical_background": "None (inferred)", "preferred_style": "Step-by-step"},
        instructions=DEFAULT_GENERATOR_INSTRUCTIONS,
    ))
    Path("/tmp/lesson_preview.md").write_text(draft.lesson_markdown)
    print(f"\nTITLE: {draft.title}\nWORDS: {len(draft.lesson_markdown.split())}\nSaved to /tmp/lesson_preview.md")
    assert draft.lesson_markdown.lstrip().startswith("#")
    assert len(draft.lesson_markdown.split()) > 400
