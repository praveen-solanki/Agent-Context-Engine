"""Fixture providers reuse existing scripted extraction and hash embeddings."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from context_graph.config import (
    ChatBackendSettings,
    EmbeddingSettings,
    LLMSettings,
    RetrySettings,
    Settings,
)
from context_graph.domain.enums import ContextType
from context_graph.domain.extraction import (
    ExtractedSignal,
    ExtractionEnvelope,
    SegmentationProposal,
)
from context_graph.providers.chat_backend import ChatTransport, EmbeddingProviderImpl
from tests.fakes import FakeEmbeddingProvider, FakeLLMProvider


def settings() -> Settings:
    return Settings(
        chat=ChatBackendSettings(
            api_key=SecretStr("fixture-only"),
            chat_model="fixture-chat",
            repair_attempts=0,
        ),
        embedding=EmbeddingSettings(
            model="fixture-embedding",
            dimension=8,
            batch_size=2,
            api_key=SecretStr("fixture-only"),
        ),
        llm=LLMSettings(context_limit_tokens=16384),
        retry=RetrySettings(max_attempts=1, base_backoff_seconds=0),
    )


def mock_providers(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def extraction(user: str, schema: type[BaseModel]) -> BaseModel:
        assert schema is ExtractionEnvelope
        signals = []
        for identifier, role, text in re.findall(
            r"\[episode_id=(\S+) role=(\w+) [^\]]*\]\n(.*?)(?=\n\[episode_id=|$)",
            user,
            re.S,
        ):
            if role == "user" and "always prefer" in text:
                signals.append(
                    ExtractedSignal(
                        concept="report_language",
                        value="Spanish" if "Spanish" in text else "English",
                        context_type=ContextType.PREFERENCE,
                        source_episode_ids=(identifier,),
                        durability_cue=True,
                        assertion_kind="asserted",
                        personal_scope=True,
                        evidence_quote=next(
                            line.removeprefix("user: ")
                            for line in text.splitlines()
                            if "always prefer" in line
                        ),
                    )
                )
        return ExtractionEnvelope(signals=tuple(signals))

    scripted = FakeLLMProvider(responder=extraction)

    async def chat(
        _: ChatTransport, path: str, payload: dict[str, Any], label: str
    ) -> dict[str, Any]:
        assert path == "chat/completions"
        calls.append({"kind": "chat", "label": label, "payload": payload})
        text = payload["messages"][-1]["content"]
        if label in {"ExtractionEnvelope", "SegmentationProposal"}:
            schema = (
                ExtractionEnvelope
                if label == "ExtractionEnvelope"
                else SegmentationProposal
            )
            answer = (
                await scripted.structured(
                    system="", user=text, schema=schema, max_output_tokens=1000
                )
            ).model_dump(mode="json")
        elif label == "BenchmarkSummary":
            answer = {
                "summary": "The current report language is Spanish."
                if "Spanish" in text
                else "The current report language is English."
            }
        elif label == "BenchmarkAnswer":
            body = json.loads(text)
            context = body["context"]
            unknown = "unrevealed" in body["question"] or not context
            answer = {
                "answer": "I do not know."
                if unknown
                else "Spanish"
                if "Spanish" in context
                else "English",
                "abstained": unknown,
            }
        elif label == "JudgeDecision":
            body = json.loads(text)
            answer = {
                "correct": body["candidate"]["abstained"]
                if body["unanswerable"]
                else body["candidate"]["answer"] in body["references"],
                "rationale": "Synthetic fixture rule, not a semantic quality measurement.",
            }
        else:
            raise AssertionError(f"unexpected fixture schema: {label}")
        return {
            "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(answer)}}
            ],
            "usage": {
                "prompt_tokens": len(text.encode()) // 4,
                "completion_tokens": 10,
            },
        }

    embeddings = FakeEmbeddingProvider(dimension=8)

    async def embed(
        _: EmbeddingProviderImpl, payload: dict[str, Any]
    ) -> dict[str, Any]:
        calls.append({"kind": "embedding", "payload": payload})
        inputs = payload["input"]
        return {
            "data": [
                {"index": index, "embedding": vector}
                for index, vector in enumerate(await embeddings.embed(inputs))
            ],
            "usage": {"prompt_tokens": sum(len(text) for text in inputs) // 4},
        }

    monkeypatch.setattr(ChatTransport, "_post_once", chat)
    monkeypatch.setattr(EmbeddingProviderImpl, "_post", embed)
    return calls
