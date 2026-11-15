"""Checks that quoted evidence really appears in the lesson (catches invented evidence)."""

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

MIN_QUOTE_CHARS = 12
MATCH_RATIO = 0.8  # tolerate tiny copying differences, not invented sentences
_STRIP = " .\"'…"
_REPLACEMENTS = {"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*+])\s+", re.M)  # "1. ", "2) ", "- ", "* "


def normalise_text(text: str) -> str:
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    text = _LIST_MARKER.sub("", text)
    text = re.sub(r"[*_`#>]", " ", text.lower())
    return " ".join(text.split())


def _found(part: str, lesson: str) -> bool:
    if part in lesson:
        return True
    match = SequenceMatcher(None, lesson, part, autojunk=False).find_longest_match(0, len(lesson), 0, len(part))
    return match.size >= MATCH_RATIO * len(part)


def _parts(quote: str) -> list[str]:
    """Split a quote at '...' and at sentence ends, so quotes spanning list items are checked piece by piece."""
    pieces: list[str] = []
    for chunk in re.split(r"\.\.\.|…", normalise_text(quote)):
        pieces += re.split(r"(?<=[.!?:])\s+", chunk)
    return [p.strip(_STRIP) for p in pieces if len(p.strip(_STRIP)) >= MIN_QUOTE_CHARS]


def quote_in_lesson(quote: str, lesson_normalised: str) -> bool:
    """True if the quote is ANCHORED in the lesson: at least one meaningful sentence really appears in it.

    Fully invented evidence is still rejected; a real sentence followed by a paraphrase is tolerated
    (live runs showed models often paraphrase the tail of a quote).
    """
    return any(_found(p, lesson_normalised) for p in _parts(quote))


def verified_quotes(quotes: Iterable[str], lesson_markdown: str) -> list[str]:
    lesson = normalise_text(lesson_markdown)
    return [q for q in quotes if quote_in_lesson(q, lesson)]
