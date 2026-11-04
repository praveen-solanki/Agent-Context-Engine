"""Project labels never select graph identity in authenticated event ingestion."""

from __future__ import annotations

from typing import cast

from neo4j import AsyncDriver
import pytest

from agent_context.assembly import AssembleRequest, TokenBudget
from agent_context.bridge import scoped_id, to_session
from agent_context.contracts import Stream
from agent_context.events import append_event
from agent_context.retrieval import Neo4jCandidateSource
from context_graph.config import PromotionSettings
from context_graph.domain.enums import ContextType, ScopeType
from context_graph.domain.extraction import ExtractedSignal, ScopeCue
from context_graph.pipeline.policy import ScopeAssignment, UnresolvedSignal, WriterPolicy
from tests.factories import single_span_episodes
from tests.unit.test_event_contracts import event, principal


class RecordingDriver:
    parameters: dict[str, object]

    async def execute_query(
        self, _query: object, **parameters: object
    ) -> tuple[list[dict[str, object]], None, None]:
        self.parameters = parameters
        return [], None, None


@pytest.mark.parametrize("project_id", ["p1", "Release_2026", "project:other"])
@pytest.mark.parametrize("label", [None, "invented-model-label"])
async def test_project_writes_and_reads_share_authenticated_identity(
    project_id: str, label: str | None
) -> None:
    actor = principal(projects=[project_id])
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id=project_id)
    stream = append_event(stream, actor, event(project_id=project_id), max_events=8)
    session = to_session(stream)
    episode = single_span_episodes(session)[0]
    signal = ExtractedSignal(
        concept="deployment_region", value="region-west", context_type=ContextType.FACT,
        scope_cue=ScopeCue(scope_type=ScopeType.PROJECT, scope_ref=label),
        source_episode_ids=(episode.episode_id,),
    )
    decision = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert isinstance(decision, ScopeAssignment)
    driver = RecordingDriver()
    source = Neo4jCandidateSource(cast(AsyncDriver, driver), database="test", tenant_id="t1")
    await source.fetch(
        actor,
        AssembleRequest(agent_id="a1", session_id="s2", project_id=project_id,
                        budget=TokenBudget(model_context_tokens=1000)),
        limit=10,
    )
    assert decision.scope_type == ScopeType.PROJECT
    assert decision.scope_id == driver.parameters["project_id"]
    assert decision.scope_id == scoped_id("t1", project_id)
    assert decision.subject_user_id == driver.parameters["user_id"]
    assert scoped_id("t1", project_id) != scoped_id("t2", project_id)
    # The trusted binding is not added to immutable message metadata.
    assert session.messages[0].metadata == {
        "event_id": "e1", "tenant_id": "t1", "event_kind": "user_message"
    }


def test_project_cue_without_authorized_binding_does_not_create_a_project() -> None:
    actor = principal()
    stream = append_event(Stream(tenant_id="t1", user_id="u1", session_id="s1"),
                          actor, event(), max_events=8)
    session = to_session(stream)
    episode = single_span_episodes(session)[0]
    signal = ExtractedSignal(
        concept="release_date", value="next month",
        scope_cue=ScopeCue(scope_type=ScopeType.PROJECT, scope_ref="invented"),
        source_episode_ids=(episode.episode_id,),
    )
    decision = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert isinstance(decision, UnresolvedSignal)
    assert decision.reason == "unresolved_scope"
