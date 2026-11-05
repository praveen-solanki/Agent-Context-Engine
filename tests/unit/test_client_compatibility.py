"""Unused additive contract fields must not break existing API deployments."""

import json

import httpx

from agent_context.assembly import AssembleRequest, ContextBundle, TokenBudget
from agent_context.client import AgentContextClient
from agent_context.contracts import EventInput, EventKind, utcnow
from agent_context.handoff import HandoffArtifact, HandoffInput


async def test_basic_requests_omit_unused_fields_but_preserve_required_preconditions() -> (
    None
):
    def serve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["agent_id"] == "agent" and body["session_id"] == "session"
        assert "task_id" not in body and "task_version" not in body
        assert body["budget"]["model_context_tokens"] == 10000
        assert "reserved_output_tokens" not in body["budget"]
        return httpx.Response(
            200,
            json=ContextBundle(
                bundle_id="old",
                tokenizer_version="utf8-byte-bound-v1",
                items=(),
                rendered="",
                token_count=0,
                exclusions=(),
                excluded_counts={},
            ).model_dump(mode="json"),
        )

    client = AgentContextClient(
        base_url="http://test",
        bearer_token="x" * 40,
        transport=httpx.MockTransport(serve),
    )
    try:
        await client.assemble_context(
            AssembleRequest(
                agent_id="agent",
                session_id="session",
                budget=TokenBudget(model_context_tokens=10000),
            )
        )
    finally:
        await client.aclose()


async def test_snapshot_defaults_and_false_tool_outcomes_keep_their_meaning() -> None:
    def serve(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v1/handoffs":
            assert body["expected_version"] == 0
            assert (
                not {
                    "status",
                    "cancelled",
                    "dependencies",
                    "must_keep",
                    "task_state_version",
                    "source_event_id",
                }
                & body.keys()
            )
            value = HandoffInput.model_validate(body)
            assert value.pending == ()
            return httpx.Response(
                200,
                json=HandoffArtifact(version=1, content=value).model_dump(mode="json"),
            )
        assert body["tool_succeeded"] is False and body["tool_call_id"] == "call"
        return httpx.Response(
            202,
            json={
                "session_id": "session",
                "recorded_sequence": 1,
                "available_sequence": 0,
                "state": "recorded",
                "attempts": 0,
            },
        )

    client = AgentContextClient(
        base_url="http://test",
        bearer_token="x" * 40,
        transport=httpx.MockTransport(serve),
    )
    try:
        await client.prepare_handoff(
            HandoffInput(
                handoff_id="handoff",
                idempotency_key="one",
                expected_version=0,
                project_id="project",
                task_id="task",
                source_session_id="session",
                goal="Continue",
            )
        )
        await client.record_events(
            EventInput(
                event_id="result",
                session_id="session",
                agent_id="agent",
                sequence=1,
                event_time=utcnow(),
                kind=EventKind.TOOL_RESULT,
                text="Failed tool call",
                tool_call_id="call",
                tool_succeeded=False,
            )
        )
    finally:
        await client.aclose()
