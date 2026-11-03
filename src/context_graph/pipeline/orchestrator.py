"""Ingestion orchestration (A.5, A.11).

Order is fixed: persist Episodes, gate, select unprocessed work from the
checkpoint, batch by tokens, extract, validate, store the extraction result,
resolve, write context and evidence, then advance the checkpoint. Episode
persistence is never blocked by extraction or maintenance.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from itertools import groupby
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from context_graph.config import Settings
from context_graph.domain.context import Lineage
from context_graph.domain.conversation import Episode, SessionInput
from context_graph.domain.enums import (
    EpisodeState,
    GateDecision,
    SegmentationStrategy,
    SourceTrust,
)
from context_graph.domain.extraction import ExtractedSignal, ExtractionBatch
from context_graph.errors import ContextGraphError
from context_graph.graph.neo4j_store import Neo4jGraphStore
from context_graph.ledger.models import RunRecord, SegmentationRecord
from context_graph.ledger.mongo import MongoLedger
from context_graph.observability import get_logger, log_event
from context_graph.pipeline.batching import TokenBatcher
from context_graph.pipeline.extractor import ExtractionService
from context_graph.pipeline.gate import RelevanceGate
from context_graph.pipeline.policy import POLICY_VERSION, ScopeAssignment, WriterPolicy
from context_graph.pipeline.promotion import PromotionService
from context_graph.pipeline.resolution import ConceptResolver, embedding_text
from context_graph.pipeline.rolling_state import RollingSessionState
from context_graph.pipeline.segmentation import EpisodeBuilder
from context_graph.pipeline.similarity_segmentation import SimilarityEpisodeBuilder
from context_graph.pipeline.writer import ContextWriter
from context_graph.prompts import PROMPT_VERSION
from context_graph.providers.base import EmbeddingProvider, LLMProvider

_logger = get_logger("pipeline.orchestrator")


@runtime_checkable
class EpisodeSegmenter(Protocol):
    """Groups a session's messages into bounded episodes.

    :class:`~context_graph.pipeline.segmentation.EpisodeBuilder` and
    :class:`~context_graph.pipeline.similarity_segmentation.SimilarityEpisodeBuilder`
    both satisfy this; :attr:`context_graph.config.SegmentationSettings.strategy`
    selects which one the pipeline uses.
    """

    async def build(self, session: SessionInput) -> list[Episode]: ...


class IngestionReport(BaseModel):
    """Outcome of one ingestion call."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    session_id: str
    episodes_persisted: int = 0
    episodes_gated_out: int = 0
    episodes_considered: int = 0
    batches_processed: int = 0
    batches_failed: int = 0
    signals_extracted: int = 0
    contexts_written: int = 0
    contexts_superseded: int = 0
    contexts_revoked: int = 0
    signals_unresolved: int = 0
    checkpoint_sequence: int = -1
    promoted_context_ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


class _SessionProgress(BaseModel):
    """Mutable counters for one ingestion call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    episodes_persisted: int = 0
    episodes_gated_out: int = 0
    episodes_considered: int = 0
    batches_processed: int = 0
    batches_failed: int = 0
    signals_extracted: int = 0
    contexts_written: int = 0
    contexts_superseded: int = 0
    contexts_revoked: int = 0
    signals_unresolved: int = 0
    errors: list[str] = Field(default_factory=list)


class IngestionPipeline:
    """The single ingestion pipeline behind the public ingestion tool."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: Neo4jGraphStore,
        ledger: MongoLedger,
        llm: LLMProvider,
        embeddings: EmbeddingProvider,
        run_id: str,
    ) -> None:
        self._settings = settings
        self._store = store
        self._ledger = ledger
        self._llm = llm
        self._embeddings = embeddings
        self._run_id = run_id

        self._episodes = self._build_segmenter(
            llm=llm, embeddings=embeddings, settings=settings
        )
        self._gate = RelevanceGate(settings.gate)
        self._batcher = TokenBatcher(llm, settings.llm, settings.batching)
        self._extractor = ExtractionService(
            llm=llm,
            ledger=ledger,
            llm_settings=settings.llm,
            retry_settings=settings.retry,
        )
        self._policy = WriterPolicy(settings.promotion)
        self._concepts = ConceptResolver(
            store=store,
            llm=llm,
            settings=settings.resolution,
            retry_settings=settings.retry,
        )
        self._writer = ContextWriter(store)
        self._promotion = PromotionService(
            store=store,
            policy=self._policy,
            batch_size=settings.maintenance.candidate_batch_size,
        )
        self._lineage = Lineage(
            run_id=run_id,
            extractor_model=llm.model,
            prompt_version=PROMPT_VERSION,
            policy_version=POLICY_VERSION,
            embedding_model=embeddings.model,
            embedding_dimension=embeddings.dimension,
        )

    @staticmethod
    def _build_segmenter(
        *, llm: LLMProvider, embeddings: EmbeddingProvider, settings: Settings
    ) -> EpisodeSegmenter:
        """Pick the episode segmenter named by ``settings.segmentation.strategy``."""
        if settings.segmentation.strategy is SegmentationStrategy.SIMILARITY:
            return SimilarityEpisodeBuilder(
                embeddings=embeddings, settings=settings.segmentation.similarity
            )
        return EpisodeBuilder(
            llm=llm,
            llm_settings=settings.llm,
            settings=settings.segmentation,
            retry_settings=settings.retry,
        )

    @property
    def run_id(self) -> str:
        return self._run_id

    async def prepare(self) -> None:
        """Create schema and ledger indexes, and record this run."""
        await self._store.ensure_schema(self._embeddings.dimension)
        await self._ledger.ensure_indexes()
        await self._ledger.upsert_run(
            RunRecord(
                run_id=self._run_id,
                graph_database=self._settings.neo4j.database,
                lineage=self._lineage,
            )
        )

    async def ingest(self, session: SessionInput) -> IngestionReport:
        """Ingest a session: persist evidence first, then derive context."""
        progress = _SessionProgress()
        episodes = await self._segment(session)
        await self._store.persist_session(session)
        progress.episodes_persisted = await self._store.persist_episodes(episodes)

        state = RollingSessionState(
            max_items=self._settings.batching.rolling_state_max_items,
            token_budget=self._settings.llm.rolling_state_token_budget,
            estimate_tokens=self._llm.estimate_tokens,
        )
        ordered_sequences: list[int] = []
        checkpoint = await self._ledger.checkpoint(self._run_id, session.session_id)
        cursor = checkpoint.checkpoint_sequence

        while True:
            episodes = await self._store.episodes_after(
                session.session_id, cursor, self._settings.batching.fetch_limit
            )
            if not episodes:
                break
            cursor = episodes[-1].sequence
            ordered_sequences.extend(episode.sequence for episode in episodes)
            log_event(
                _logger,
                "ingestion.episodes_discovered",
                session_id=session.session_id,
                count=len(episodes),
                state=EpisodeState.DISCOVERED.value,
            )
            await self._process_page(session, episodes, state, progress)

        advanced = await self._ledger.advance_checkpoint(
            self._run_id, session.session_id, ordered_sequences
        )
        promoted = await self._run_maintenance(progress)

        report = IngestionReport(
            run_id=self._run_id,
            session_id=session.session_id,
            checkpoint_sequence=advanced.checkpoint_sequence,
            promoted_context_ids=tuple(promoted),
            errors=tuple(progress.errors),
            **progress.model_dump(exclude={"errors"}),
        )
        log_event(
            _logger,
            "ingestion.checkpointed",
            session_id=session.session_id,
            checkpoint=advanced.checkpoint_sequence,
            state=EpisodeState.CHECKPOINTED.value,
        )
        log_event(
            _logger,
            "ingestion.completed",
            **report.model_dump(exclude={"errors", "promoted_context_ids"}),
        )
        return report

    async def _segment(self, session: SessionInput) -> list[Episode]:
        """Group the session into episodes, reusing this run's earlier grouping.

        Grouping is model-assisted, so a resumed run must not regroup: the
        stored result keeps episode identities stable and prevents duplicates.
        """
        messages = session.ordered_messages()
        fingerprints = [
            hashlib.sha256(
                json.dumps(
                    [session.user_id, message.model_dump(mode="json")],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for message in messages
        ]
        stored = await self._ledger.segmentation(self._run_id, session.session_id)
        previous: list[Episode] = []
        offset = 0
        if stored is not None:
            previous = [Episode.model_validate(episode) for episode in stored.episodes]
            offset = stored.message_count
            if len(messages) < offset:
                raise ValueError(
                    "incremental session cannot remove previously recorded messages"
                )
            if stored.message_fingerprints:
                if fingerprints[:offset] != stored.message_fingerprints:
                    raise ValueError(
                        "incremental session cannot modify recorded messages or identity"
                    )
            else:
                # Legacy records predate fingerprints: verify exact source spans
                # before upgrading rather than trusting a matching message count.
                by_id = {message.message_id: message for message in messages[:offset]}
                spans = [span for episode in previous for span in episode.spans]
                for message in messages[:offset]:
                    parts = sorted(
                        (s for s in spans if s.message_id == message.message_id),
                        key=lambda s: s.char_start,
                    )
                    if (
                        not parts
                        or "".join(s.text for s in parts) != message.text
                        or parts[0].char_start != 0
                        or parts[-1].char_end != len(message.text)
                        or any(
                            left.char_end != right.char_start
                            for left, right in zip(parts, parts[1:])
                        )
                    ):
                        raise ValueError(
                            "legacy segmentation does not match supplied messages"
                        )
                if any(
                    s.message_id not in by_id
                    or s.role != by_id[s.message_id].role
                    or s.sequence != by_id[s.message_id].sequence
                    or s.metadata != by_id[s.message_id].metadata
                    or s.timestamp != by_id[s.message_id].timestamp
                    or s.sender_id != session.speaker_of(by_id[s.message_id])
                    for s in spans
                ):
                    raise ValueError("legacy segmentation identity mismatch")
            if (
                len(messages) > offset
                and offset
                and messages[offset].sequence <= messages[offset - 1].sequence
            ):
                raise ValueError("new messages must follow recorded sequence")
        if (
            stored is not None
            and offset == len(messages)
            and stored.message_fingerprints
        ):
            log_event(
                _logger,
                "segmentation.reused",
                session_id=session.session_id,
                episodes=len(stored.episodes),
            )
            return previous

        tail = session.model_copy(update={"messages": tuple(messages[offset:])})
        if session.metadata.get("ace_derive_context") is False:
            deterministic = EpisodeBuilder(
                llm=self._llm,
                llm_settings=self._settings.llm,
                settings=self._settings.segmentation,
                retry_settings=self._settings.retry,
            )
            additions = deterministic.build_deterministic(tail)
        else:
            additions = await self._episodes.build(tail) if tail.messages else []
        if session.metadata.get("ace_event_bridge") is True:
            # A model may group a user instruction with hostile tool text.
            # Enforce trust boundaries from exact spans after segmentation so
            # an episode's first speaker cannot launder the other speaker.
            separated: list[Episode] = []
            for episode in additions:
                for _, group in groupby(
                    episode.spans, key=lambda span: span.source_type.trust
                ):
                    separated.append(
                        Episode.from_spans(
                            session_id=session.session_id,
                            sequence=0,
                            spans=tuple(group),
                        )
                    )
            additions = separated
        ordinal = max((episode.sequence for episode in previous), default=-1)
        episodes = previous + [
            episode.model_copy(update={"sequence": ordinal + index})
            for index, episode in enumerate(additions, start=1)
        ]
        await self._ledger.save_segmentation(
            SegmentationRecord(
                run_id=self._run_id,
                session_id=session.session_id,
                message_count=len(session.messages),
                message_fingerprints=fingerprints,
                episodes=[episode.model_dump(mode="json") for episode in episodes],
            )
        )
        return episodes

    async def ingest_many(
        self, sessions: Sequence[SessionInput]
    ) -> list[IngestionReport]:
        """Ingest independent sessions concurrently, bounded by configuration.

        Sessions are independent; windows inside one session are not, and stay
        strictly ordered inside :meth:`ingest`.
        """
        limit = asyncio.Semaphore(self._settings.segmentation.max_concurrent_sessions)

        async def run(session: SessionInput) -> IngestionReport:
            async with limit:
                return await self.ingest(session)

        return list(await asyncio.gather(*(run(session) for session in sessions)))

    async def _process_page(
        self,
        session: SessionInput,
        episodes: Sequence[Episode],
        state: RollingSessionState,
        progress: _SessionProgress,
    ) -> None:
        """Gate a page of Episodes and extract context from what remains."""
        extractable = await self._gate_page(
            episodes,
            session.session_id,
            progress,
            trusted_only=session.metadata.get("ace_event_bridge") is True,
            derive_context=session.metadata.get("ace_derive_context") is not False,
        )
        for batch in self._batcher.batches(
            self._run_id, session.session_id, extractable
        ):
            await self._process_batch(session, batch, state, progress)

    async def _gate_page(
        self,
        episodes: Sequence[Episode],
        session_id: str,
        progress: _SessionProgress,
        *,
        trusted_only: bool = False,
        derive_context: bool = True,
    ) -> list[Episode]:
        """Apply the cheap relevance gate.

        A skipped Episode has nothing to extract, so it counts as completed work
        and must not hold the checkpoint back.
        """
        extractable: list[Episode] = []
        skipped: list[int] = []
        for episode in episodes:
            if not derive_context or (
                trusted_only
                and any(
                    span.source_type.trust is not SourceTrust.FIRST_PARTY
                    for span in episode.spans
                )
            ):
                skipped.append(episode.sequence)
                progress.episodes_considered += 1
                continue
            progress.episodes_considered += 1
            if self._gate.decide(episode) is GateDecision.SKIP:
                skipped.append(episode.sequence)
                log_event(
                    _logger,
                    "gate.episode_skipped",
                    episode_id=episode.episode_id,
                    state=EpisodeState.GATED_SKIPPED.value,
                )
                continue
            extractable.append(episode)

        progress.episodes_gated_out += len(skipped)
        await self._ledger.record_completed(self._run_id, session_id, skipped)
        return extractable

    async def _process_batch(
        self,
        session: SessionInput,
        batch: ExtractionBatch,
        state: RollingSessionState,
        progress: _SessionProgress,
    ) -> None:
        """Extract, resolve and write one batch, then record its outcome."""
        episodes = {chunk.episode_id: chunk.episode for chunk in batch.chunks}
        try:
            envelope = await self._extractor.extract(batch, state.render())
            progress.signals_extracted += len(envelope.signals)
            embeddings = await self._embed(envelope.signals)
            for signal in envelope.signals:
                await self._apply_signal(
                    session, signal, episodes, embeddings, progress
                )
            await self._recall_references(
                session, envelope.unresolved_references, state
            )
        except ContextGraphError as error:
            progress.batches_failed += 1
            progress.errors.append(f"{batch.batch_key}: {error}")
            await self._ledger.record_failed(
                self._run_id, session.session_id, batch.sequences
            )
            await self._ledger.mark_failed(self._run_id, batch.batch_key, str(error))
            log_event(
                _logger,
                "ingestion.batch_failed",
                batch_key=batch.batch_key,
                sequences=list(batch.sequences),
                error=str(error),
            )
            return

        state.update(envelope.signals)
        progress.batches_processed += 1
        await self._ledger.record_completed(
            self._run_id, session.session_id, batch.sequences
        )
        await self._ledger.mark_committed(self._run_id, batch.batch_key)
        log_event(
            _logger,
            "ingestion.batch_committed",
            batch_key=batch.batch_key,
            sequences=list(batch.sequences),
            state=EpisodeState.GRAPH_COMMITTED.value,
        )

    async def _apply_signal(
        self,
        session: SessionInput,
        signal: ExtractedSignal,
        episodes: dict[str, Episode],
        embeddings: dict[str, list[float]],
        progress: _SessionProgress,
    ) -> None:
        """Resolve and write a single signal."""
        if (
            session.metadata.get("ace_event_bridge") is True
            and isinstance(signal.value, str)
            and signal.value.casefold().strip()
            in self._settings.llm.unresolved_reference_values
        ):
            progress.signals_unresolved += 1
            return
        primary = min(
            (
                episodes[episode_id]
                for episode_id in signal.source_episode_ids
                if episode_id in episodes
            ),
            key=lambda episode: episode.sequence,
            default=None,
        )
        if primary is None:
            progress.signals_unresolved += 1
            return

        decision = self._policy.decide(signal, session, primary)
        if not isinstance(decision, ScopeAssignment):
            progress.signals_unresolved += 1
            log_event(
                _logger,
                "policy.signal_unresolved",
                concept=signal.concept,
                reason=decision.reason,
                detail=decision.detail,
            )
            return

        vector = embeddings[embedding_text(signal)]
        resolution = await self._concepts.resolve(signal, vector)
        result = await self._writer.write(
            signal=signal,
            resolution=resolution,
            decision=decision,
            session=session,
            episodes=episodes,
            lineage=self._lineage,
            embedding=vector,
        )
        if not result.revoked_context_ids:
            progress.contexts_written += 1
        progress.contexts_superseded += len(result.superseded_context_ids)
        progress.contexts_revoked += len(result.revoked_context_ids)

    async def _recall_references(
        self,
        session: SessionInput,
        references: Sequence[str],
        state: RollingSessionState,
    ) -> None:
        """Look up stale references instead of replaying the whole session (A.6)."""
        if not references:
            return
        vectors = await self._embeddings.embed(list(references))
        for reference, vector in zip(references, vectors, strict=True):
            matches = await self._store.search_contexts(
                embedding=vector,
                top_k=1,
                subject_user_id=session.user_id,
            )
            if not matches:
                log_event(_logger, "reference.unresolved", reference=reference)
                continue
            context, score = matches[0]
            if score < self._settings.resolution.ambiguous_similarity:
                log_event(
                    _logger,
                    "reference.unresolved",
                    reference=reference,
                    best_score=round(score, 4),
                )
                continue
            state.recall(reference, f"{context.concept_key}={context.value}")
            log_event(
                _logger,
                "reference.recalled",
                reference=reference,
                context_id=context.context_id,
                score=round(score, 4),
            )

    async def _embed(
        self, signals: Sequence[ExtractedSignal]
    ) -> dict[str, list[float]]:
        """Embed the batch with one provider call; one vector serves each signal."""
        texts = list(dict.fromkeys(embedding_text(signal) for signal in signals))
        if not texts:
            return {}
        vectors = await self._embeddings.embed(texts)
        return dict(zip(texts, vectors, strict=True))

    async def _run_maintenance(self, progress: _SessionProgress) -> Iterable[str]:
        """Run promotion; a maintenance failure never fails ingestion."""
        try:
            return await self._promotion.run()
        except ContextGraphError as error:
            progress.errors.append(f"promotion: {error}")
            log_event(_logger, "maintenance.failed", error=str(error))
            return ()
