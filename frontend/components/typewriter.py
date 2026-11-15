"""Typing effect for text that is already complete (lessons are shown only after the workflow saves them)."""

import re
import time
from collections.abc import Iterator

MAX_SECONDS = 8.0   # long lessons never take longer than this to appear
MAX_DELAY = 0.03    # short replies still look natural


def chunk_text(text: str, words_per_chunk: int = 2) -> list[str]:
    """Split into small pieces that keep every space and newline (so Markdown renders correctly)."""
    tokens = re.findall(r"\S+\s*|\s+", text)
    return ["".join(tokens[i:i + words_per_chunk]) for i in range(0, len(tokens), words_per_chunk)]


def typewriter(text: str, max_seconds: float = MAX_SECONDS) -> Iterator[str]:
    chunks = chunk_text(text)
    delay = min(MAX_DELAY, max_seconds / max(len(chunks), 1))
    for chunk in chunks:
        yield chunk
        time.sleep(delay)
