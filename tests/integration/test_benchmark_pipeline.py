"""Small native fixtures through real HTTP/outbox/stores, no paid providers.

Requires an explicitly selected EMPTY dedicated graph via
ACE_BENCHMARK_TEST_NEO4J_URI. Never points the destructive scratch reset at the
ordinary integration graph or the user-facing stack.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from agent_context.benchmarks import cli
from agent_context.benchmarks.backend import ACEBackend, ScratchWorkspace
from agent_context.benchmarks.datasets import acquire, prepare
from agent_context.benchmarks.models import Experiment
from agent_context.benchmarks.providers import Providers
from agent_context.benchmarks.reports import summarize
from agent_context.benchmarks.runner import run
from context_graph.config import MongoSettings, Neo4jSettings
from tests.benchmark_support import mock_providers, settings
from tests.unit.test_benchmark_datasets import fixture_dataset

pytestmark = pytest.mark.skipif(
    not os.environ.get("ACE_BENCHMARK_TEST_NEO4J_URI"),
    reason="requires an explicitly selected empty benchmark fixture graph",
)


async def test_native_fixture_suite_real_ace_and_legacy_with_mocked_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = mock_providers(monkeypatch)
    datasets = tuple(
        fixture_dataset(name, limit=1)
        for name in ("longmemeval", "convomem", "locomo", "normalized")
    )
    config = Experiment(
        name="integration-fixture",
        datasets=datasets,
        artifacts=tmp_path,
        context_bytes=2000,
        scoring="judge",
        max_provider_requests=200,
        exclusive_scratch_stores=True,
    )
    for dataset in datasets:
        await acquire(dataset, config, tmp_path)
        prepare(dataset, config, tmp_path)
    resolved = settings().model_copy(
        update={
            "neo4j": Neo4jSettings(
                uri=os.environ["ACE_BENCHMARK_TEST_NEO4J_URI"],
                password=SecretStr("fixture-only"),
            ),
            "mongo": MongoSettings(
                uri="mongodb://127.0.0.1:27017", database="ace_benchmark_" + uuid4().hex
            ),
        }
    )
    workspace = ScratchWorkspace(resolved, "fixture-" + uuid4().hex)
    providers = Providers(resolved, config)
    backend = ACEBackend(workspace, providers, config)
    try:
        await workspace.claim()
        directory = await run(config, tmp_path, providers, backend)
        summary = json.loads(summarize(directory).read_text())
        assert summary["completed"] and summary["scored_trials"] == 24
        assert all(row["failed_trials"] == 0 for row in summary["summary"].values())
        index = json.loads((directory / "run.json").read_text())
        for name in index["case_files"]:
            result = json.loads((directory / name).read_text())
            assert result["ingestion_details"]["message_events"] >= 1
            ace = next(row for row in result["trials"] if row["method"] == "ace")
            assert ace["answer"] and ace["judge"]["correct"]
            assert ace["scores"]["evidence_turn_recall"] in (None, 1)
            assert result["ingestion"]["usage"]["ingestion"]["attempts"] >= 1
        assert any(call.get("label") == "ExtractionEnvelope" for call in calls)
        assert any(call.get("label") == "BenchmarkAnswer" for call in calls)
        assert any(call["kind"] == "embedding" for call in calls)
        # An attempt to claim these populated stores must neither reset data
        # nor remove the original owner's claim, even with the same run ID.
        contender = ScratchWorkspace(resolved, workspace.run_id)
        try:
            with pytest.raises(ValueError, match="empty"):
                await contender.claim()
            await workspace.require_owner()
        finally:
            await contender.close()
        await workspace.release()
        rows, _, _ = await workspace.driver.execute_query(
            "MATCH(n) RETURN count(n) AS count", database_=resolved.neo4j.database
        )
        assert rows[0]["count"] == 0
        assert not await workspace.db["ace_benchmark_workspace"].find_one({})
    finally:
        await backend.close_case()
        if workspace.claimed:
            await workspace.release()
        await workspace.mongo.drop_database(resolved.mongo.database)
        await workspace.close()
        await providers.close()


async def test_cli_prepare_execute_report_and_zero_call_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = mock_providers(monkeypatch)
    resolved = settings().model_copy(
        update={
            "neo4j": Neo4jSettings(
                uri=os.environ["ACE_BENCHMARK_TEST_NEO4J_URI"],
                password=SecretStr("fixture-only"),
            ),
            "mongo": MongoSettings(
                uri="mongodb://127.0.0.1:27017", database="ace_benchmark_" + uuid4().hex
            ),
        }
    )
    monkeypatch.setattr(cli, "Settings", lambda: resolved)
    config = Experiment(
        name="cli-fixture",
        datasets=(fixture_dataset("convomem", limit=1),),
        artifacts=tmp_path / "artifacts",
        context_bytes=2000,
        scoring="judge",
        exclusive_scratch_stores=True,
    )
    path = tmp_path / "experiment.json"
    path.write_text(config.model_dump_json())
    args = argparse.Namespace(
        command="prepare",
        config=path,
        dataset=[],
        limit=None,
        all_cases=False,
        max_requests=None,
        execute=False,
        resume=None,
    )
    await cli.execute(args)
    assert calls == []
    args.command = "run"
    assert isinstance(await cli.execute(args), dict) and not calls
    args.execute = True
    directory = await cli.execute(args)
    assert isinstance(directory, Path)
    summary_path = await cli.execute(argparse.Namespace(command="score", run=directory))
    assert isinstance(summary_path, Path)
    assert json.loads(summary_path.read_text())["completed"]
    assert len(json.loads((directory / "run.json").read_text())["case_files"]) == 1
    before = len(calls)
    args.resume = directory
    assert await cli.execute(args) == directory
    assert len(calls) == before
    # Both store claims are released after the command; no test data survives.
    workspace = ScratchWorkspace(resolved, directory.name)
    try:
        await workspace.claim()
        await workspace.release()
        await workspace.mongo.drop_database(resolved.mongo.database)
    finally:
        await workspace.close()
