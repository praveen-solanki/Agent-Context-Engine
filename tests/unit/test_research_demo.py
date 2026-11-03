"""Deterministic host boundary tests without treating model output as execution."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_context.demo import DemoSettings, ResearchAssistant, ResearchDecision
from agent_context.client import AgentContextClient
from tests.fakes import FakeLLMProvider


@pytest.mark.parametrize("payload", [{}, {"answer": "done", "read_document_id": "doc"}])
def test_model_must_choose_one_action(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        ResearchDecision.model_validate(payload)


async def test_document_registry_is_bounded_before_any_model_or_network_call() -> None:
    user = AgentContextClient(base_url="http://unused", bearer_token="x" * 40)
    host = AgentContextClient(base_url="http://unused", bearer_token="y" * 40)
    try:
        with pytest.raises(ValueError, match="bounds"):
            ResearchAssistant(
                user_client=user,
                host_client=host,
                llm=FakeLLMProvider(),
                documents={"doc": "x" * 20},
                settings=DemoSettings(max_document_bytes=10),
            )
    finally:
        await user.aclose()
        await host.aclose()
