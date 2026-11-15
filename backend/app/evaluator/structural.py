"""Deterministic Python checks that need no AI: structure, length, readability, abbreviations."""

import re
from statistics import mean

from app.evaluator.schemas import StructuralFinding

MIN_WORDS = 400
MAX_WORDS = 3000
MIN_SECTIONS = 4
MAX_AVG_SENTENCE_WORDS = 26
SUMMARY_HEADING_WORDS = ("summary", "recap", "takeaway", "conclusion", "wrap", "review", "what you learned")
ACRONYM_ALLOWLIST = frozenset({"OK", "TV", "UK", "USA", "AM", "PM"})

_H1 = re.compile(r"^#\s+\S", re.M)
_H2 = re.compile(r"^##\s+(.+)$", re.M)
_CODE = re.compile(r"```.*?```", re.S)
_ACRONYM = re.compile(r"\b([A-Z]{2,5})s?\b")


def _fail(criterion: str, message: str) -> StructuralFinding:
    return StructuralFinding(criterion=criterion, severity="fail", message=message)


def _warn(criterion: str, message: str) -> StructuralFinding:
    return StructuralFinding(criterion=criterion, severity="warning", message=message)


def prose_of(markdown: str) -> str:
    """Lesson text without code blocks and headings."""
    text = _CODE.sub(" ", markdown)
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def average_sentence_words(markdown: str) -> float:
    prose = re.sub(r"[*_`>\[\]()]", " ", prose_of(markdown))
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", prose) if re.search(r"\w", s)]
    lengths = [len(re.findall(r"\b\w+\b", s)) for s in sentences]
    return mean(lengths) if lengths else 0.0


def is_expanded(abbreviation: str, text: str) -> bool:
    a = re.escape(abbreviation)
    patterns = (
        rf"\(\s*{a}s?\s*\)",                                              # artificial intelligence (AI)
        rf"\b{a}s?\s*\(",                                                 # RAG (Retrieval-Augmented ...)
        rf"\b{a}s?\s+(?:stands for|means|is short for|is an?|is the)\b",  # LLM stands for ...
        rf"\b(?:called|shortened to|known as)\s+(?:an?\s+|the\s+)?{a}\b",  # ... known as an LLM
    )
    return any(re.search(pattern, text) for pattern in patterns)


def run_structural_checks(markdown: str) -> list[StructuralFinding]:
    findings: list[StructuralFinding] = []
    prose = prose_of(markdown)

    words = len(re.findall(r"\b\w+\b", prose))
    if words < MIN_WORDS:
        findings.append(_fail("topic_coverage",
                              f"The lesson is too short ({words} words) to explain the topic fully; "
                              f"aim for at least {MIN_WORDS} words."))
    elif words > MAX_WORDS:
        findings.append(_warn("beginner_friendliness",
                              f"The lesson is very long ({words} words) and may overwhelm a beginner."))

    titles = len(_H1.findall(markdown))
    if titles != 1:
        findings.append(_fail("teaching_flow", f"The lesson needs exactly one '# ' title line (found {titles})."))

    headings = [h.strip().lower() for h in _H2.findall(markdown)]
    if len(headings) < MIN_SECTIONS:
        findings.append(_fail("teaching_flow",
                              f"The lesson has {len(headings)} '## ' sections; organise it into at least "
                              f"{MIN_SECTIONS} clear sections."))
    summary_positions = [i for i, h in enumerate(headings) if any(w in h for w in SUMMARY_HEADING_WORDS)]
    if not summary_positions:
        findings.append(_fail("teaching_flow", "The lesson has no summary section ('## Summary' or similar) at the end."))
    elif summary_positions[-1] < len(headings) - 2:
        findings.append(_warn("teaching_flow", "The summary section is not near the end of the lesson."))

    average = average_sentence_words(markdown)
    if average > MAX_AVG_SENTENCE_WORDS:
        findings.append(_fail("beginner_friendliness",
                              f"Sentences average {average:.0f} words; beginners need shorter sentences "
                              "(aim for under 20)."))

    for abbreviation in sorted(set(_ACRONYM.findall(prose)) - ACRONYM_ALLOWLIST):
        if not is_expanded(abbreviation, markdown):
            findings.append(_warn("jargon_explanation",
                                  f"The abbreviation '{abbreviation}' does not appear to be expanded or explained."))
    return findings
