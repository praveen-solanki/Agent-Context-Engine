"""Diagnostics preserve correlation without leaking nested source data."""

import json
import logging

import pytest

from context_graph.observability import _JsonFormatter  # pyright: ignore[reportPrivateUsage]


@pytest.fixture(autouse=True)
def capture_structured_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging.getLogger("context_graph"), "propagate", True)


def test_nested_private_keys_and_credentials_are_redacted() -> None:
    record = logging.LogRecord(
        "context_graph.test", logging.INFO, __file__, 1, "stage", (), None
    )
    record.context = {
        "rows": [{"text": "PRIVATE_SOURCE", "count": 2}],
        "headers": {"Authorization": "PRIVATE_TOKEN", "X-Api-Key": "PRIVATE_KEY"},
        "exception": ValueError("PRIVATE_EXCEPTION"),
    }
    raw = _JsonFormatter().format(record)
    assert "PRIVATE" not in raw
    assert json.loads(raw)["rows"][0]["count"] == 2


def test_structured_fields_cannot_replace_log_envelope() -> None:
    record = logging.LogRecord(
        "context_graph.test", logging.INFO, __file__, 1, "stage", (), None
    )
    record.context = {"event": "forged_event", "level": "forged_level", "count": 1}
    data = json.loads(_JsonFormatter().format(record))
    assert data["event"] == "stage"
    assert data["level"] == "INFO"
    assert data["count"] == 1


async def test_request_context_is_isolated_between_concurrent_tasks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import asyncio
    from context_graph.observability import get_logger, log_context, log_event

    ready = asyncio.Event()
    logger = get_logger("correlation-test")

    async def work(identifier: str) -> None:
        with log_context(request_id=identifier):
            await ready.wait()
            with log_context(stage_id="nested"):
                log_event(logger, "nested")
            log_event(logger, "outer")

    with caplog.at_level(logging.INFO, logger=logger.name):
        tasks = [asyncio.create_task(work(identifier)) for identifier in ("one", "two")]
        ready.set()
        await asyncio.gather(*tasks)
        log_event(logger, "outside")
    rows = [
        json.loads(_JsonFormatter().format(record))
        for record in caplog.records
        if record.name == logger.name
    ]
    assert {(row["event"], row.get("request_id")) for row in rows} == {
        ("nested", "one"),
        ("nested", "two"),
        ("outer", "one"),
        ("outer", "two"),
        ("outside", None),
    }
    assert all("stage_id" not in row for row in rows if row["event"] != "nested")


async def test_stage_measures_errors_and_cancellation_without_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import asyncio
    import pytest
    from context_graph.observability import get_logger, stage

    logger = get_logger("stage-test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(ValueError):
            with stage(logger, "operation"):
                raise ValueError("PRIVATE_DETAILS")
        with pytest.raises(asyncio.CancelledError):
            with stage(logger, "operation"):
                raise asyncio.CancelledError("PRIVATE_CANCEL")
    rows = [
        json.loads(_JsonFormatter().format(record))
        for record in caplog.records
        if record.name == logger.name
    ]
    assert [row["outcome"] for row in rows] == ["error", "cancelled"]
    assert all(row["duration_seconds"] >= 0 for row in rows)
    assert "PRIVATE" not in json.dumps(rows)


async def test_http_logs_use_route_templates_and_server_request_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import httpx
    from fastapi import FastAPI
    from agent_context.api import HTTPBoundary

    app = FastAPI()
    app.add_middleware(HTTPBoundary)

    @app.get("/items/{identifier}")
    async def read(identifier: str):
        return {"ok": bool(identifier)}

    with caplog.at_level(logging.INFO, logger="context_graph.api"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/items/PRIVATE_PATH?secret=PRIVATE_QUERY",
                headers={"X-Request-ID": "PRIVATE_FORGED"},
            )
    rows = [
        json.loads(_JsonFormatter().format(record))
        for record in caplog.records
        if record.name == "context_graph.api"
    ]
    assert len(rows) == 1
    assert rows[0]["route"] == "/items/{identifier}"
    assert rows[0]["request_id"] == response.headers["x-request-id"]
    assert rows[0]["status_code"] == 200
    assert "PRIVATE" not in json.dumps(rows)


def test_recursive_metadata_is_bounded_without_stringifying_arbitrary_objects() -> None:
    class Private:
        def __str__(self) -> str:
            raise AssertionError("must not stringify arbitrary objects")

    record = logging.LogRecord(
        "context_graph.test", logging.INFO, __file__, 1, "bounded", (), None
    )
    recursive: dict[str, object] = {"object": Private()}
    recursive["cycle"] = recursive
    record.context = recursive
    row = json.loads(_JsonFormatter().format(record))
    assert row["object"] == "[unsupported]"
