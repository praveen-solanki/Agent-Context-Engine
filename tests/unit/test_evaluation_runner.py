"""The real comparison loop retains failures, equalizes inputs and repeats all methods."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from types import TracebackType
from typing import Any, Self

import pytest

from agent_context import evaluation
from agent_context.assembly import AssembleRequest, ContextBundle
from agent_context.contracts import RecordedEvent, Stream
from context_graph.errors import ProviderError
from context_graph.providers.chat_backend import ChatTransport
from tests.unit.test_event_contracts import event


async def test_comparison_runs_all_six_methods_and_retains_a_failed_trial(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "docs/ace/results/live-demo-verified-20261104.json"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ACE_TENANT_ID", "ace-live")
    monkeypatch.setenv("ACE_USER_ID", "research-user")
    monkeypatch.setenv("ACE_DEMO_USER_TOKEN", "x" * 40)
    requests: list[dict[str, Any]] = []
    embedding_modes: list[bool] = []

    class Client:
        def __init__(self, **_: object) -> None:
            pass

        async def session(self, identifier: str) -> Stream:
            return Stream(
                tenant_id="ace-live",
                user_id="research-user",
                session_id=identifier,
                events=(
                    RecordedEvent(
                        event=event(session_id=identifier),
                        actor_id="user",
                        actor_kind="user",
                    ),
                ),
            )

        async def assemble_context(self, request: AssembleRequest) -> ContextBundle:
            return ContextBundle(
                bundle_id="frozen",
                tokenizer_version="utf8-byte-bound-v1",
                items=(),
                rendered="Current report language is Spanish",
                token_count=34,
                exclusions=(),
                excluded_counts={},
            )

        async def aclose(self) -> None:
            pass

    class Embeddings:
        model = "test-embedding"
        dimension = 2

        def __init__(self, *, for_query: bool = False, **_: object) -> None:
            embedding_modes.append(for_query)

        async def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

        async def aclose(self) -> None:
            pass

    class OldResult:
        def as_prompt_block(self) -> str:
            return "Current report language is Spanish"

    class Retriever:
        def __init__(self, *args: object, **kwargs: object) -> None:
            assert "embeddings" in kwargs

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(
            self,
            kind: type[BaseException] | None,
            error: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            pass

        async def retrieve(self, user: str, query: str) -> OldResult:
            return OldResult()

    async def response(
        self: ChatTransport, path: str, payload: dict[str, Any], label: str
    ) -> dict[str, Any]:
        if label == "Summary":
            answer = {"summary": "The current language is Spanish"}
        else:
            requests.append(payload)
            if len(requests) == 1:
                raise ProviderError("test-only invalid provider response")
            answer = {
                "report_language": "Spanish",
                "recommended_option": "A",
                "evidence": ["research-brief"],
            }
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(answer)}}
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }

    monkeypatch.setattr(evaluation, "AgentContextClient", Client)
    monkeypatch.setattr(evaluation, "EmbeddingProviderImpl", Embeddings)
    monkeypatch.setattr(evaluation, "Neo4jContextRetriever", Retriever)
    monkeypatch.setattr(ChatTransport, "_post_once", response)
    path = await evaluation.evaluate(
        source, options=evaluation.EvaluationSettings(trials=3)
    )
    result = json.loads(path.read_text())
    assert result["evaluation_finished"] and result["failed_trials"] == 1
    assert len(result["results"]) == len(requests) == 18
    assert len(result["summary"]) == len(result["contexts"]) == 6
    assert all(row["trials"] == 3 for row in result["summary"].values())
    assert sum(row["successful_trials"] for row in result["summary"].values()) == 17
    assert embedding_modes == [False, True]
    for seed in range(3):
        assert sum(request["seed"] == seed for request in requests) == 6
    failed = [row for row in result["results"] if row["error_type"]]
    assert failed[0]["failed_attempts"] == 1 and not failed[0]["usage_complete"]
    assert all(row["context_bytes_upper_bound"] <= 4000 for row in result["results"])
    assert all(
        json.loads(request["messages"][1]["content"])["documents"] == result["document"]
        for request in requests
    )
