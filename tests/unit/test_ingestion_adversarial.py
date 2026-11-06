"""Adversarial budget and partial-episode recovery contracts, without providers."""

from __future__ import annotations

import pytest

from context_graph.config import BatchingSettings, LLMSettings, Settings
from context_graph.domain.conversation import SessionInput
from context_graph.domain.extraction import ExtractionBatch, ExtractionEnvelope
from context_graph.errors import ExtractionValidationError
from context_graph.pipeline.batching import TokenBatcher
from context_graph.pipeline.orchestrator import IngestionPipeline
from tests.factories import make_message, single_span_episode
from tests.fakes import (
    FakeEmbeddingProvider,
    FakeLLMProvider,
    InMemoryGraphStore,
    InMemoryLedger,
)


class UnevenTokenizer(FakeLLMProvider):
    """A local estimator with deliberately uneven token density across scripts."""

    def estimate_tokens(self, text: str) -> int:
        return sum(5 if ord(char) > 127 else 1 for char in text)


def limits(budget: int) -> LLMSettings:
    return LLMSettings(
        context_limit_tokens=budget + 1000,
        max_output_tokens=500,
        prompt_overhead_tokens=200,
        safety_margin_tokens=200,
        rolling_state_token_budget=100,
    )


def test_chunks_fit_local_budget_with_uneven_unicode_token_density() -> None:
    llm = UnevenTokenizer()
    episode = single_span_episode(
        "S1", make_message(1, "a" * 80 + "漢" * 80 + "🙂" * 40)
    )
    chunks = TokenBatcher(llm, limits(50), BatchingSettings()).chunk(episode)
    assert "".join(chunk.text for chunk in chunks) == episode.text
    assert all(chunk.token_estimate <= 50 for chunk in chunks)
    assert all(
        chunk.token_estimate == llm.estimate_tokens(chunk.text) for chunk in chunks
    )
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.chunk_count == len(chunks) for chunk in chunks)


@pytest.mark.parametrize("failure_position", ["first", "last"])
async def test_one_failed_episode_chunk_cannot_be_checkpointed_by_another_success(
    monkeypatch: pytest.MonkeyPatch, failure_position: str
) -> None:
    llm, ledger, store = FakeLLMProvider(), InMemoryLedger(), InMemoryGraphStore()
    pipeline = IngestionPipeline(
        settings=Settings(),
        store=store,
        ledger=ledger,
        llm=llm,
        embeddings=FakeEmbeddingProvider(),
        run_id="partial-episode",
    )
    batcher = TokenBatcher(llm, limits(25), BatchingSettings(overlap_episodes=0))
    monkeypatch.setattr(pipeline, "_batcher", batcher)
    session = SessionInput(
        session_id="S1",
        user_id="U1",
        messages=(make_message(1, "remember this " * 40),),
    )
    episode = single_span_episode("S1", session.messages[0])
    batches = batcher.batches(pipeline.run_id, "S1", [episode])
    assert len(batches) > 1
    failed_key = batches[0 if failure_position == "first" else -1].batch_key
    fail_once = True

    async def extract(
        batch: ExtractionBatch, rolling_state: str = ""
    ) -> ExtractionEnvelope:
        nonlocal fail_once
        await ledger.start_batch(batch)
        if batch.batch_key == failed_key and fail_once:
            fail_once = False
            raise ExtractionValidationError("one extraction chunk failed")
        return ExtractionEnvelope()

    monkeypatch.setattr(pipeline._extractor, "extract", extract)  # pyright: ignore[reportPrivateUsage]
    await pipeline.prepare()
    first = await pipeline.ingest(session)
    assert first.batches_failed == 1
    assert first.checkpoint_sequence == -1
    checkpoint = await ledger.checkpoint(pipeline.run_id, session.session_id)
    assert checkpoint.failed_sequences == [0]
    assert 0 not in checkpoint.completed_above

    resumed = await pipeline.ingest(session)
    assert resumed.batches_failed == 0
    assert resumed.checkpoint_sequence == 0
    assert (
        await ledger.checkpoint(pipeline.run_id, session.session_id)
    ).failed_sequences == []
    assert len(store.episodes) == 1


@pytest.mark.parametrize("system_chars", [700, 1600])
async def test_full_prompt_can_use_reserved_instruction_space_without_double_reserving(
    monkeypatch: pytest.MonkeyPatch, system_chars: int
) -> None:
    from context_graph.config import RetrySettings
    from context_graph.pipeline.extractor import ExtractionService

    monkeypatch.setattr(
        "context_graph.pipeline.extractor.EXTRACTION_SYSTEM", "p" * system_chars
    )
    service = ExtractionService(
        llm=FakeLLMProvider(),
        ledger=InMemoryLedger(),
        llm_settings=limits(1000),
        retry_settings=RetrySettings(),
    )
    # Content is 900 tokens; system brings the full request to 1075 or 1300.
    # The full input allowance is 2000 - 500 output - 200 safety = 1300.
    await service._verify_token_budget("x" * 3600)  # pyright: ignore[reportPrivateUsage]


async def test_instruction_growth_is_checked_even_with_short_episode_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from context_graph.config import RetrySettings
    from context_graph.pipeline.extractor import ExtractionService

    monkeypatch.setattr(
        "context_graph.pipeline.extractor.EXTRACTION_SYSTEM", "p" * 5200
    )
    service = ExtractionService(
        llm=FakeLLMProvider(),
        ledger=InMemoryLedger(),
        llm_settings=limits(1000),
        retry_settings=RetrySettings(),
    )
    with pytest.raises(ExtractionValidationError):
        await service._verify_token_budget("x" * 4)  # pyright: ignore[reportPrivateUsage]


def test_unrepresentable_single_character_budget_fails_without_losing_source() -> None:
    llm = UnevenTokenizer()
    episode = single_span_episode("S1", make_message(1, "漢"))
    with pytest.raises(ExtractionValidationError, match="one character"):
        TokenBatcher(llm, limits(1), BatchingSettings()).chunk(episode)
    assert episode.content == "漢"
