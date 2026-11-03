"""Structured logging for the ingestion pipeline (A.10 observability)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_EXTRA_KEY = "context"
_configured = False
_PRIVATE_FIELDS = frozenset(
    {
        "concept",
        "concept_key",
        "detail",
        "reference",
        "text",
        "value",
        "query",
        "error",
        "source_text",
    }
)


class _JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        extra = getattr(record, _EXTRA_KEY, None)
        if isinstance(extra, dict):
            payload.update(
                {
                    key: "[redacted]" if key in _PRIVATE_FIELDS else value
                    for key, value in extra.items()
                }
            )
        if record.exc_info:
            payload["error_type"] = (
                record.exc_info[0].__name__ if record.exc_info[0] else "unknown"
            )
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", log_file: str | None = None) -> None:
    """Install console and file handlers once per process."""
    global _configured
    if _configured:
        return
    root = logging.getLogger("context_graph")
    root.setLevel(level.upper())
    root.propagate = False

    console = logging.StreamHandler()
    console.setFormatter(_JsonFormatter())
    root.addHandler(console)

    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(_JsonFormatter())
        root.addHandler(file_handler)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a pipeline logger; use ``extra={"context": {...}}`` for fields."""
    return logging.getLogger(f"context_graph.{name}")


def log_event(
    logger: logging.Logger, event: str, /, level: int = logging.INFO, **fields: Any
) -> None:
    """Log a structured pipeline event with arbitrary diagnostic fields."""
    logger.log(level, event, extra={_EXTRA_KEY: fields})
