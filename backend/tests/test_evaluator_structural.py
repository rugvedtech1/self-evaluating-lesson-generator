"""Deterministic structural checks."""

import pytest

from app.evaluator.structural import run_structural_checks

FILLER = "This is a short and clear sentence for a beginner. " * 30


def _lesson(*, titles: int = 1, sections=("Intro", "Basics", "Details", "Example"),
            summary: str | None = "Summary", body: str = FILLER) -> str:
    parts = ["# Title"] * titles
    for heading in sections:
        parts += [f"## {heading}", body]
    if summary:
        parts += [f"## {summary}", "A short recap of the key ideas."]
    return "\n\n".join(parts)


def _fails(markdown: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in run_structural_checks(markdown):
        if f.severity == "fail":
            out.setdefault(f.criterion, []).append(f.message)
    return out


def _warnings(markdown: str) -> list[str]:
    return [f.message for f in run_structural_checks(markdown) if f.severity == "warning"]


def test_too_short_lesson_fails_topic_coverage() -> None:
    assert "topic_coverage" in _fails(_lesson(body="Too short."))


@pytest.mark.parametrize("titles", [0, 2])
def test_lesson_needs_exactly_one_title(titles: int) -> None:
    assert "teaching_flow" in _fails(_lesson(titles=titles))


def test_too_few_sections_fails_teaching_flow() -> None:
    assert "teaching_flow" in _fails(_lesson(sections=("Only one", "Two")))


def test_missing_summary_fails_teaching_flow() -> None:
    messages = _fails(_lesson(summary=None)).get("teaching_flow", [])
    assert any("summary" in m for m in messages)


def test_summary_far_from_end_is_a_warning() -> None:
    markdown = _lesson(sections=("Intro", "Summary", "A", "B", "C"), summary=None)
    assert "teaching_flow" not in _fails(markdown)
    assert any("not near the end" in w for w in _warnings(markdown))


def test_very_long_sentences_fail_beginner_friendliness() -> None:
    long_sentences = ("word " * 40 + ". ") * 15
    assert "beginner_friendliness" in _fails(_lesson(body=long_sentences))


@pytest.mark.parametrize("sentence", [
    "Artificial intelligence (AI) helps people.",
    "RAG (Retrieval-Augmented Generation) is useful.",
    "LLM stands for large language model.",
    "A large language model is also known as an LLM.",
    "An API is a way for programs to talk to each other.",
])
def test_expanded_abbreviations_are_not_flagged(sentence: str) -> None:
    assert not any("abbreviation" in w for w in _warnings(_lesson(body=sentence + " " + FILLER)))


def test_unexpanded_abbreviation_is_flagged() -> None:
    warnings = _warnings(_lesson(body="We query the HNSW index quickly. " + FILLER))
    assert any("'HNSW'" in w for w in warnings)
