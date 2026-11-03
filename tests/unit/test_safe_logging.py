"""General pipeline diagnostics must not emit private prompt or response data."""

import json
import logging

from context_graph.observability import _JsonFormatter  # pyright: ignore[reportPrivateUsage]


def test_private_fields_and_exception_values_are_redacted() -> None:
    record = logging.LogRecord(
        "context_graph.test", logging.ERROR, __file__, 1, "model_failed", (), None
    )
    record.context = {
        "value": "SENSITIVE_VALUE",
        "error": "SENSITIVE_RESPONSE",
        "concept_key": "private_project_name",
        "count": 3,
    }
    try:
        raise ValueError("SENSITIVE_EXCEPTION")
    except ValueError as error:
        record.exc_info = (type(error), error, error.__traceback__)
    payload = _JsonFormatter().format(record)
    assert "SENSITIVE" not in payload and "private_project_name" not in payload
    parsed = json.loads(payload)
    assert parsed["count"] == 3 and parsed["error_type"] == "ValueError"
