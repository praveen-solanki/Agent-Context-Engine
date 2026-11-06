"""Structured logging for the ingestion pipeline (A.10 observability)."""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from time import perf_counter
from itertools import islice
from pathlib import Path
from typing import Any

_EXTRA_KEY = "context"
_configured = False
_correlation: ContextVar[dict[str, Any] | None] = ContextVar(
    "log_correlation", default=None
)
_ENVELOPE_FIELDS = frozenset({"ts", "level", "logger", "event"})
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
        "prompt",
        "response",
        "body",
        "exception",
        "authorization",
        "cookie",
        "setcookie",
        "password",
        "secret",
        "token",
        "apikey",
        "xapikey",
        "accesstoken",
        "refreshtoken",
    }
)


_NORMALIZED_PRIVATE_FIELDS = frozenset(
    field.replace("_", "") for field in _PRIVATE_FIELDS
)


def _redact(value: Any, *, key: str = "", depth: int = 0) -> Any:
    normalized = key.casefold().replace("_", "").replace("-", "")
    if normalized in _NORMALIZED_PRIVATE_FIELDS:
        return "[redacted]"
    if depth >= 8:
        return "[bounded]"
    if isinstance(value, Mapping):
        return {
            str(k): _redact(v, key=str(k), depth=depth + 1)
            for k, v in islice(value.items(), 128)
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, depth=depth + 1) for item in value[:128]]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return "[unsupported]"


@contextmanager
def log_context(**fields: Any) -> Generator[None]:
    """Attach request/stream metadata to concurrent logs without global state."""
    token = _correlation.set({**(_correlation.get() or {}), **fields})
    try:
        yield
    finally:
        _correlation.reset(token)


@contextmanager
def stage(logger: logging.Logger, event: str, **fields: Any) -> Generator[None]:
    """Measure a stage without logging input, output, or exception content."""
    started = perf_counter()
    outcome = "success"
    error_type: str | None = None
    try:
        yield
    except BaseException as error:
        outcome = "cancelled" if type(error).__name__ == "CancelledError" else "error"
        error_type = type(error).__name__
        raise
    finally:
        measured: dict[str, Any] = {
            **fields,
            "outcome": outcome,
            "error_type": error_type,
            "duration_seconds": perf_counter() - started,
        }
        log_event(logger, event, **measured)


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
                    str(key): _redact(value, key=str(key))
                    for key, value in extra.items()
                    if key not in _ENVELOPE_FIELDS
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
    logger.log(
        level, event, extra={_EXTRA_KEY: {**(_correlation.get() or {}), **fields}}
    )
