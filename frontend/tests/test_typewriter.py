"""The typing effect must never alter the text, and must never take too long."""

from components.typewriter import chunk_text, typewriter


def test_chunks_reassemble_to_exactly_the_original_markdown() -> None:
    text = "# Title\n\nHello  world.\n- item one\n- item two\n\n## Next\nEnd."
    assert "".join(chunk_text(text)) == text


def test_typing_time_is_bounded_for_long_lessons(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("components.typewriter.time.sleep", sleeps.append)
    text = "word " * 5000
    assert "".join(typewriter(text, max_seconds=8.0)) == text
    assert sum(sleeps) <= 8.0 + 1e-6
