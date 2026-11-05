"""Actual experiment loop and providers, with only external services mocked."""

from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import pytest

from agent_context.benchmarks.datasets import acquire, prepare
from agent_context.benchmarks.models import Case, ContextView, Experiment, Pricing
from agent_context.benchmarks.providers import Providers, RequestLimitExceeded
from agent_context.benchmarks.reports import summarize
from agent_context.benchmarks.runner import run
from agent_context.benchmarks.scoring import token_f1
from context_graph.errors import TransientError
from context_graph.providers.chat_backend import ChatTransport
from tests.benchmark_support import mock_providers, settings
from tests.unit.test_benchmark_datasets import fixture_dataset


class Backend:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.ingested: list[str] = []
        self.closed = False

    async def ingest(self, case: Case) -> dict[str, object]:
        self.ingested.append(case.id)
        if self.fail:
            raise ConnectionError("fixture ingestion failure")
        return {"fixture": True}

    async def ace(self, case: Case, budget: int) -> ContextView:
        return ContextView(
            text="The current language is Spanish.",
            source_turns=case.evidence_turns,
            source_sessions=case.evidence_sessions,
        )

    async def legacy(self, case: Case) -> str:
        return "The current language is Spanish."

    async def close_case(self) -> None:
        self.closed = True


async def prepared(tmp_path: Path, **changes: object) -> Experiment:
    dataset = fixture_dataset("longmemeval", limit=None)
    config = Experiment.model_validate(
        {
            "name": "fixture",
            "datasets": [dataset.model_dump()],
            "artifacts": tmp_path,
            "trials": 2,
            "context_bytes": 2000,
            "max_provider_requests": 300,
            **changes,
        }
    )
    await acquire(dataset, config, tmp_path)
    prepare(dataset, config, tmp_path)
    return config


async def test_six_methods_equal_inputs_judging_costs_and_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = mock_providers(monkeypatch)
    config = await prepared(
        tmp_path,
        scoring="judge",
        prices={
            "fixture-chat": Pricing(input_per_million_usd=1, output_per_million_usd=2),
            "fixture-embedding": Pricing(input_per_million_usd=1),
        },
    )
    providers = Providers(settings(), config)
    backend = Backend()
    try:
        directory = await run(config, tmp_path, providers, backend)
        report = json.loads(summarize(directory).read_text())
        assert report["completed"] and report["scored_trials"] == 24
        assert backend.closed and len(backend.ingested) == 2
        assert len(report["summary"]) == 6
        assert all(
            row["attempted_trials"] == 4 and row["answer_p95_seconds"] is None
            for row in report["summary"].values()
        )
        answer_calls = [
            row["payload"] for row in calls if row.get("label") == "BenchmarkAnswer"
        ]
        assert len(answer_calls) == 24
        assert len({row["model"] for row in answer_calls}) == 1
        assert len({row["messages"][0]["content"] for row in answer_calls}) == 1
        assert all(
            set(json.loads(row["messages"][-1]["content"]))
            == {"question", "question_date", "context"}
            for row in answer_calls
        )
        stages = report["stage_totals_current_attempts"]
        assert stages["preparation/vector_top_k"]["known_cost_usd"] is not None
        assert stages["answer_and_judge/ace"]["usage"]["judge"]["attempts"] == 4
        assert len(list((directory / "exports").glob("*.jsonl"))) == 12
        before = len(calls)
        await run(config, tmp_path, providers, backend, resume=directory)
        assert len(calls) == before  # completed cases cause no provider work
        changed = config.model_copy(update={"context_bytes": 1500})
        with pytest.raises(ValueError, match="resume inputs"):
            await run(changed, tmp_path, providers, backend, resume=directory)
    finally:
        await providers.close()


async def test_ingestion_failure_does_not_remove_baseline_trials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_providers(monkeypatch)
    config = await prepared(tmp_path)
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, Backend(fail=True))
        summary = json.loads(summarize(directory).read_text())["summary"]
        assert summary["longmemeval/ace"]["failed_trials"] == 4
        assert summary["longmemeval/existing_retriever"]["failed_trials"] == 4
        assert summary["longmemeval/full_history"]["failed_trials"] == 0
        assert all(row["attempted_trials"] == 4 for row in summary.values())
    finally:
        await providers.close()


async def test_request_cap_keeps_incomplete_report_and_missing_cost_is_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["full_history"], max_provider_requests=1)
    providers = Providers(settings(), config)
    try:
        with pytest.raises(RequestLimitExceeded):
            await run(config, tmp_path, providers, None)
        assert len(calls) == providers.budget.used == 1
        directory = next((tmp_path / "runs").iterdir())
        summary = json.loads(summarize(directory).read_text())
        assert not summary["completed"]
        assert (
            summary["stage_totals_current_attempts"]["answer_and_judge/full_history"][
                "known_cost_usd"
            ]
            is None
        )
    finally:
        await providers.close()


def test_unicode_f1_and_abstention_are_not_keyword_success() -> None:
    assert token_f1("SPANISH!", "Spanish") == 1
    assert token_f1("Café", "café") == 1
    assert token_f1("", "Spanish") == 0


@pytest.mark.parametrize("value", [None, -1, True, "12", "malformed-object", [1]])
async def test_invalid_usage_never_becomes_known_zero_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    config = await prepared(
        tmp_path,
        methods=["full_history"],
        prices={"fixture-chat": Pricing(input_per_million_usd=1)},
    )

    async def reply(*_: object) -> dict[str, object]:
        return {
            "usage": value
            if value == "malformed-object" or isinstance(value, list)
            else {"prompt_tokens": value, "completion_tokens": 0}
        }

    monkeypatch.setattr(ChatTransport, "_post_once", reply)
    providers = Providers(settings(), config)
    try:
        before, started = providers.snapshot(), perf_counter()
        await providers.transports["answer"].post(
            "chat/completions", {}, "usage-fixture"
        )
        measurement = providers.measure(before, started)
        assert measurement.usage["answer"].unreported == 1
        assert measurement.known_cost_usd is None
    finally:
        await providers.close()


async def test_request_ceiling_applies_to_provider_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from context_graph.config import RetrySettings

    config = await prepared(tmp_path, methods=["full_history"], max_provider_requests=2)
    calls = 0

    async def fail(*_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise TransientError("fixture retry")

    monkeypatch.setattr(ChatTransport, "_post_once", fail)
    providers = Providers(
        settings().model_copy(
            update={"retry": RetrySettings(max_attempts=5, base_backoff_seconds=0)}
        ),
        config,
    )
    try:
        with pytest.raises(RequestLimitExceeded):
            await providers.transports["answer"].post(
                "chat/completions", {}, "retry-fixture"
            )
        assert calls == providers.budget.used == 2
    finally:
        await providers.close()


async def test_saved_judge_cannot_validate_a_changed_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["full_history"], scoring="judge")
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, None)
        index = json.loads((directory / "run.json").read_text())
        target = directory / index["case_files"][0]
        result = json.loads(target.read_text())
        result["trials"][0]["answer"]["answer"] = (
            "An unsupported answer replacing the original."
        )
        target.write_text(json.dumps(result))
        report = json.loads(summarize(directory).read_text())
        assert report["summary"]["longmemeval/full_history"]["failed_trials"] >= 1
    finally:
        await providers.close()


async def test_resume_retains_failed_attempt_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["full_history"], max_provider_requests=1)
    providers = Providers(settings(), config)
    try:
        with pytest.raises(RequestLimitExceeded):
            await run(config, tmp_path, providers, None)
        directory = next((tmp_path / "runs").iterdir())
        # A new invocation receives the same configured per-invocation limit.
        resume_providers = Providers(settings(), config)
        with pytest.raises(RequestLimitExceeded):
            await run(
                config,
                tmp_path,
                resume_providers,
                None,
                resume=directory,
            )
        await resume_providers.close()
        report = json.loads(summarize(directory).read_text())
        assert report["archived_incomplete_attempts"]
        stage = "answer_and_judge/full_history"
        assert (
            report["stage_totals_including_archived_attempts"][stage]["usage"][
                "answer"
            ]["attempts"]
            == 2
        )
    finally:
        await providers.close()
