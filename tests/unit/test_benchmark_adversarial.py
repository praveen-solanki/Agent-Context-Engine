"""Boundary regressions for native benchmark inputs, fixtures and stage evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_context.benchmarks.datasets import adapt
from agent_context.benchmarks.models import Experiment
from agent_context.benchmarks.providers import Providers
from context_graph.domain.extraction import ExtractionEnvelope
from tests.benchmark_support import mock_providers, settings
from tests.unit.test_benchmark_datasets import FIXTURES, fixture_dataset


def test_premixed_convomem_accepts_outer_history_without_item_history() -> None:
    item = json.loads((FIXTURES / "convomem.json").read_text())["evidence_items"][0]
    conversations = item.pop("conversations")
    outer = {"evidenceItems": [item], "conversations": conversations, "contextSize": 2}
    case = next(
        adapt(outer, fixture_dataset("convomem"), "changing_evidence/test.json")
    )
    assert len(case.sessions) == 2
    assert case.evidence_turns == ("new:0",)


async def test_scripted_extraction_quotes_source_text_not_rendered_speaker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_providers(monkeypatch)
    config = Experiment(
        name="fixture-quotes",
        datasets=(fixture_dataset("convomem"),),
        artifacts=tmp_path,
    )
    providers = Providers(settings(), config)
    text = "I always prefer Spanish for reports."
    try:
        envelope = await providers.llms["ingestion"].structured(
            system="fixture",
            user=f"[episode_id=ep-1 role=user timestamp=2026-01-01]\nuser: {text}",
            schema=ExtractionEnvelope,
            max_output_tokens=500,
        )
        assert len(envelope.signals) == 1
        assert envelope.signals[0].evidence_quote == text
    finally:
        await providers.close()


def test_source_precision_is_null_without_labels_and_penalizes_distractors() -> None:
    from agent_context.benchmarks.scoring import precision

    assert precision(None, ("gold",)) is None
    assert precision(("selected",), ()) is None
    assert precision((), ("gold",)) == 0
    assert precision(("gold", "noise", "gold"), ("gold",)) == 0.5


async def test_reports_separate_ingestion_and_answer_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.benchmarks.reports import summarize
    from agent_context.benchmarks.runner import run
    from tests.unit.test_benchmark_runner import Backend, prepared

    mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["ace", "full_history"])
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, Backend(fail=True))
        summary = json.loads(summarize(directory).read_text())["summary"]
        assert summary["longmemeval/ace"]["failure_stages"] == {"ingestion": 4}
        assert summary["longmemeval/full_history"]["failure_stages"] == {}
        assert summary["longmemeval/ace"]["error_types"] == {"ConnectionError": 4}
    finally:
        await providers.close()


@pytest.mark.parametrize("field,value", [("question", " \n"), ("answers", [" "])])
def test_blank_question_or_reference_cannot_be_a_valid_benchmark(
    field: str, value: object
) -> None:
    from agent_context.benchmarks.models import Case

    row = json.loads((FIXTURES / "normalized.json").read_text())[0]
    row[field] = value
    with pytest.raises(
        ValueError, match="question and reference answers must be nonblank"
    ):
        Case.model_validate(row)


async def test_retrieval_evidence_is_scored_even_when_answer_generation_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.benchmarks.reports import summarize
    from agent_context.benchmarks.runner import run
    from context_graph.errors import ProviderError
    from context_graph.providers.chat_backend import ChatTransport
    from tests.unit.test_benchmark_runner import Backend, prepared

    config = await prepared(tmp_path, methods=["ace"], trials=1)

    async def fail(*_: object) -> dict[str, object]:
        raise ProviderError("synthetic answer failure")

    monkeypatch.setattr(ChatTransport, "_post_once", fail)
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, Backend())
        report = json.loads(summarize(directory).read_text())["summary"][
            "longmemeval/ace"
        ]
        assert report["failed_trials"] == 2
        assert report["failure_stages"] == {"answer_generation": 2}
        assert report["evidence_turn_recall"] == 1
        assert report["evidence_turn_precision"] == 1
    finally:
        await providers.close()


@pytest.mark.parametrize("stage", ["context_preparation", "judging"])
async def test_failure_stage_identifies_preparation_and_judge_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from typing import Any

    from agent_context.benchmarks.models import Case, ContextView
    from agent_context.benchmarks.reports import summarize
    from agent_context.benchmarks.runner import run
    from context_graph.providers.chat_backend import ChatTransport
    from tests.unit.test_benchmark_runner import Backend, prepared

    mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["ace"], trials=1, scoring="judge")
    backend = Backend()
    original = getattr(ChatTransport, "_post_once")

    async def fail_context(_: Case, __: int) -> ContextView:
        raise TimeoutError("synthetic retrieval timeout")

    async def fail_judge(
        transport: ChatTransport, path: str, payload: dict[str, Any], label: str
    ) -> dict[str, Any]:
        if label == "JudgeDecision":
            raise TimeoutError("synthetic judge timeout")
        return await original(transport, path, payload, label)

    if stage == "context_preparation":
        monkeypatch.setattr(backend, "ace", fail_context)
    else:
        monkeypatch.setattr(ChatTransport, "_post_once", fail_judge)
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, backend)
        row = json.loads(summarize(directory).read_text())["summary"]["longmemeval/ace"]
        assert row["failed_trials"] == 2
        assert row["failure_stages"] == {stage: 2}
    finally:
        await providers.close()


async def test_reports_keep_legacy_artifacts_without_new_diagnostics_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.benchmarks.reports import summarize
    from agent_context.benchmarks.runner import run
    from tests.unit.test_benchmark_runner import Backend, prepared

    mock_providers(monkeypatch)
    config = await prepared(tmp_path, methods=["ace"], trials=1)
    providers = Providers(settings(), config)
    try:
        directory = await run(config, tmp_path, providers, Backend())
        index = json.loads((directory / "run.json").read_text())
        for name in index["case_files"]:
            target = directory / name
            result = json.loads(target.read_text())
            for trial in result["trials"]:
                trial.pop("failure_stage")
                trial["scores"].pop("evidence_turn_precision")
                trial["scores"].pop("evidence_session_precision")
            target.write_text(json.dumps(result))
        row = json.loads(summarize(directory).read_text())["summary"]["longmemeval/ace"]
        assert row["failed_trials"] == 0
        assert row["evidence_turn_recall"] == 1
        assert row["evidence_turn_precision"] is None
    finally:
        await providers.close()


@pytest.mark.parametrize(
    "usage,unreported",
    [
        (None, True),
        ("malformed", True),
        (["unexpected"], True),
        ({"prompt_tokens": True}, True),
        ({"prompt_tokens": -1}, True),
        ({"total_tokens": 0}, False),
    ],
)
async def test_embedding_usage_preserves_valid_vectors_and_distinguishes_unknown_cost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    usage: object,
    unreported: bool,
) -> None:
    from time import perf_counter
    from typing import Any

    from agent_context.benchmarks.models import Pricing
    from context_graph.providers.chat_backend import EmbeddingProviderImpl

    config = Experiment(
        name="embedding-usage",
        datasets=(fixture_dataset("convomem"),),
        artifacts=tmp_path,
        prices={"fixture-embedding": Pricing(input_per_million_usd=1)},
    )
    expected = [1.0, *([0.0] * 7)]

    async def reply(_: EmbeddingProviderImpl, __: dict[str, Any]) -> dict[str, Any]:
        return {"data": [{"index": 0, "embedding": expected}], "usage": usage}

    monkeypatch.setattr(EmbeddingProviderImpl, "_post", reply)
    providers = Providers(settings(), config)
    try:
        before, start = providers.snapshot(), perf_counter()
        assert await providers.passages.embed(["one input"]) == [expected]
        measurement = providers.measure(before, start)
        assert measurement.usage["passage_embedding"].unreported == int(unreported)
        assert measurement.usage["passage_embedding"].failed_attempts == 0
        if unreported:
            assert measurement.known_cost_usd is None
        else:
            assert measurement.known_cost_usd == 0
    finally:
        await providers.close()
