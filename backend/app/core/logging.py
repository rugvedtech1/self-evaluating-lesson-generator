"""Structured (JSON) logging configuration."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """Format each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Extra structured fields: logger.info("msg", extra={"context": {...}})
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _AppLogHandler(logging.StreamHandler):
    """Marker class so we can replace only our own handler on re-configuration."""


def configure_logging(level: str = "INFO") -> None:
    """Attach a JSON stdout handler to the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, _AppLogHandler):
            root.removeHandler(handler)

    handler = _AppLogHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())
