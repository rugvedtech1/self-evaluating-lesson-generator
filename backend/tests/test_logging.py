"""Tests for structured JSON logging."""

import json
import logging

from app.core.logging import JsonFormatter, configure_logging


def test_json_formatter_produces_valid_json_with_context() -> None:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello %s", args=("world",), exc_info=None,
    )
    record.context = {"chat_id": "abc-123"}
    data = json.loads(JsonFormatter().format(record))
    assert data["message"] == "hello world"
    assert data["level"] == "INFO"
    assert data["logger"] == "test"
    assert data["chat_id"] == "abc-123"
    assert "timestamp" in data


def test_configure_logging_is_idempotent() -> None:
    root = logging.getLogger()
    configure_logging("DEBUG")
    configure_logging("DEBUG")
    ours = [h for h in root.handlers if type(h).__name__ == "_AppLogHandler"]
    assert len(ours) == 1
    assert root.level == logging.DEBUG
    configure_logging("INFO")
