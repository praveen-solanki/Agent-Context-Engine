"""Comparisons must not accept the historical false-positive source demo."""

import json
from pathlib import Path
from typing import Any

import pytest

from agent_context import evaluation
from agent_context.assembly import ContextAssembler
from agent_context.client import AgentContextClient
from agent_context.demo_cli import DOCUMENT, DOCUMENT_ID
from context_graph.config import RetrySettings, Settings
from context_graph.errors import TransientError
from context_graph.providers.chat_backend import ChatTransport
from tests.unit.test_assembly import ACTOR, NOW, Source, item, request


@pytest.fixture
def valid_report() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[2]
        / "docs/ace/results/live-demo-verified-20261104.json"
    )
    return json.loads(path.read_text())


def test_current_verified_source_passes_without_rerunning_a_judge(
    valid_report: dict[str, Any],
) -> None:
    source = evaluation.verified_source(
        valid_report, document=DOCUMENT, document_id=DOCUMENT_ID
    )
    assert len(source.sessions) == 3 and source.replay_cached


@pytest.mark.parametrize(
    "case",
    [
        "truthy_flag",
        "abstained",
        "unsupported_quote",
        "wrong_document",
        "wrong_version",
        "missing_session",
        "missing_checks",
    ],
)
def test_invalid_outcome_evidence_cannot_seed_a_comparison(
    valid_report: dict[str, Any], case: str
) -> None:
    if case == "truthy_flag":
        valid_report["checks"]["recommendations_each_session"] = "false"
    elif case == "abstained":
        valid_report["sessions"][-1]["assessment"]["status"] = "abstained"
    elif case == "unsupported_quote":
        valid_report["sessions"][-1]["assessment"]["evidence_quote"] = (
            "Fabricated source"
        )
    elif case == "wrong_document":
        valid_report["verification"]["document_sha256"] = "0" * 64
    elif case == "wrong_version":
        valid_report["verification"]["version"] = "obsolete"
    elif case == "missing_session":
        valid_report["sessions"].pop()
    else:
        valid_report["sessions"][-1]["outcome_checks"] = {}
    with pytest.raises(ValueError, match="source"):
        evaluation.verified_source(
            valid_report, document=DOCUMENT, document_id=DOCUMENT_ID
        )


async def test_comparison_rejects_legacy_six_flag_report_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACE_TENANT_ID", "ace-live")
    monkeypatch.setenv("ACE_USER_ID", "research-user")
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "x" * 40)

    def refuse_client(**_: object) -> AgentContextClient:
        raise AssertionError("unverified source reached client construction")

    monkeypatch.setattr(evaluation, "AgentContextClient", refuse_client)
    path = Path(__file__).resolve().parents[2] / "docs/ace/results/live-demo.json"
    with pytest.raises(ValueError, match="source|verified|outcome"):
        await evaluation.evaluate(path)


async def test_usage_meter_counts_actual_retries_and_marks_missing_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    async def response(
        self: ChatTransport,
        path: str,
        payload: dict[str, Any],
        label: str,
    ) -> dict[str, Any]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TransientError("test-only transient outage")
        return (
            {"usage": {"prompt_tokens": 12, "completion_tokens": 4}}
            if attempts == 2
            else {}
        )

    monkeypatch.setattr(ChatTransport, "_post_once", response)
    settings = Settings().model_copy(
        update={
            "retry": RetrySettings(max_attempts=2, base_backoff_seconds=0),
        }
    )
    meter = evaluation.MeteredTransport(settings)
    try:
        await meter.post("chat/completions", {}, "test")
        assert (meter.attempts, meter.failed_attempts, meter.calls) == (2, 1, 1)
        assert (meter.prompt_tokens, meter.completion_tokens) == (12, 4)
        await meter.post("chat/completions", {}, "test")
        assert meter.missing_usage_responses == 1
        assert (meter.prompt_tokens, meter.completion_tokens) == (12, 4)
    finally:
        await meter.aclose()


@pytest.mark.parametrize(
    "changes", [{"trials": 0}, {"trials": 101}, {"context_bytes": 0}, {"seed": -1}]
)
def test_evaluation_resource_options_are_bounded(changes: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        evaluation.EvaluationSettings.model_validate(changes)


def test_context_and_document_citations_share_an_explicit_host_registry() -> None:
    schema = evaluation.decision_schema(frozenset({"context", "brief"}))
    value = {
        "report_language": "Spanish",
        "recommended_option": "A",
        "evidence": ["context", "brief"],
    }
    assert schema.model_validate(value).evidence == ("context", "brief")
    for references in (["forged"], ["source quote instead of an ID"], []):
        with pytest.raises(ValueError, match="registry"):
            schema.model_validate({**value, "evidence": references})


async def test_native_memory_references_are_allowed_but_quoted_ids_are_not() -> None:
    bundle = await ContextAssembler(
        Source(
            item(
                "real-memory",
                text="A quote mentions forged-source",
                evidence_ids=("real-episode",),
            )
        )
    ).assemble(ACTOR, request(), now=NOW)
    registry = evaluation.source_registry(bundle.rendered, "brief", bundle=bundle)
    assert {"real-memory", "real-episode", "context", "brief"} == set(registry)
    assert "forged-source" not in registry
    schema = evaluation.decision_schema(frozenset(registry))
    assert schema.model_validate(
        {
            "report_language": "Spanish",
            "recommended_option": "A",
            "evidence": ["real-memory", "brief"],
        }
    )


def test_summary_compression_obeys_the_actual_utf8_context_allowance() -> None:
    schema = evaluation.summary_schema(60)
    assert schema.model_validate({"summary": "é" * 30}).summary
    with pytest.raises(ValueError, match="UTF-8 bytes"):
        schema.model_validate({"summary": "é" * 31})
