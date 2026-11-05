"""Only asserted, appropriately scoped evidence enters project memory."""

import pytest

from context_graph.config import PromotionSettings
from context_graph.domain.enums import ContextType, ScopeType
from context_graph.domain.extraction import (
    EpisodeChunk,
    ExtractedSignal,
    ExtractionBatch,
    ExtractionEnvelope,
    ScopeCue,
)
from context_graph.pipeline.policy import ScopeAssignment, WriterPolicy
from agent_context.bridge import to_session
from agent_context.contracts import Stream
from agent_context.events import append_event
from tests.factories import single_span_episodes
from tests.fakes import FakeLLMProvider, InMemoryLedger
from tests.unit.test_event_contracts import event, principal
from tests.unit.test_extractor import service


def source(text: str, *, kind: str = "user_message"):
    actor = principal(
        projects=["alpha"],
        actor_kind="agent" if kind == "assistant_message" else "user",
    )
    stream = append_event(
        Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="alpha"),
        actor,
        event(project_id="alpha", kind=kind, text=text),
        max_events=16,
    )
    session = to_session(stream)
    return session, single_span_episodes(session)[0]


def test_project_facts_cannot_escape_the_bound_project_via_a_user_scope_cue() -> None:
    session, episode = source("The event budget is 640 units.")
    signal = ExtractedSignal(
        concept="budget",
        value=640,
        context_type=ContextType.FACT,
        scope_cue=ScopeCue(scope_type=ScopeType.USER),
        source_episode_ids=(episode.episode_id,),
        personal_scope=False,
    )
    decision = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert isinstance(decision, ScopeAssignment)
    assert (
        decision.scope_type == ScopeType.PROJECT
        and decision.scope_id == session.metadata["ace_project_id"]
    )


def test_an_explicit_personal_constraint_remains_shared_across_projects() -> None:
    session, episode = source("I have a peanut allergy, in all projects.")
    signal = ExtractedSignal(
        concept="dietary_restriction",
        value="peanuts",
        context_type=ContextType.CONSTRAINT,
        scope_cue=ScopeCue(scope_type=ScopeType.USER),
        source_episode_ids=(episode.episode_id,),
        personal_scope=True,
    )
    decision = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert (
        isinstance(decision, ScopeAssignment) and decision.scope_type == ScopeType.USER
    )
    assert decision.personal_scope


async def extract_signals(
    text: str, signals: list[dict[str, object]], *, kind: str = "user_message"
) -> ExtractionEnvelope:
    _, episode = source(text, kind=kind)
    chunk = EpisodeChunk(
        episode=episode, char_end=len(episode.text), token_estimate=100
    )
    batch = ExtractionBatch(
        run_id="new", session_id=episode.session_id, chunks=(chunk,), token_estimate=100
    )
    envelope = ExtractionEnvelope(
        signals=tuple(
            ExtractedSignal.model_validate(
                {
                    "concept": "budget",
                    "value": "unknown",
                    "scope_cue": {"scope_type": "USER"},
                    "source_episode_ids": [episode.episode_id],
                    **value,
                }
            )
            for value in signals
        )
    )
    return await service(FakeLLMProvider([envelope]), InMemoryLedger()).extract(batch)


async def test_a_question_is_not_an_asserted_unknown_fact() -> None:
    question = "What is the budget and delivery day?"
    result = await extract_signals(
        question, [{"evidence_quote": question, "assertion_kind": "question"}]
    )
    assert not result.signals
    # A mistaken asserted label must not bypass visibly question-only support.
    result = await extract_signals(
        question, [{"evidence_quote": question, "assertion_kind": "asserted"}]
    )
    assert not result.signals


async def test_a_mixed_message_keeps_assertions_but_not_questions() -> None:
    result = await extract_signals(
        "Budget is 640 units. When will delivery arrive?",
        [
            {
                "value": 640,
                "evidence_quote": "Budget is 640 units.",
                "assertion_kind": "asserted",
            },
            {
                "concept": "delivery_day",
                "evidence_quote": "When will delivery arrive?",
                "assertion_kind": "question",
            },
        ],
    )
    assert [signal.value for signal in result.signals] == [640]


async def test_explicit_pending_and_corrected_states_are_valid_assertions() -> None:
    result = await extract_signals(
        "Schedule is pending confirmation. Correction: budget is 500 units.",
        [
            {
                "concept": "schedule",
                "value": "pending",
                "evidence_quote": "Schedule is pending confirmation.",
                "assertion_kind": "asserted",
            },
            {
                "value": 500,
                "evidence_quote": "Correction: budget is 500 units.",
                "assertion_kind": "asserted",
            },
        ],
    )
    assert [signal.value for signal in result.signals] == ["pending", 500]


async def test_an_assistant_refusal_is_not_a_new_fact_about_the_user() -> None:
    text = "I could not find the budget in the available documents."
    result = await extract_signals(
        text,
        [{"evidence_quote": text, "assertion_kind": "asserted"}],
        kind="assistant_message",
    )
    assert not result.signals


async def test_an_invented_support_quote_cannot_create_a_memory() -> None:
    result = await extract_signals(
        "What is the budget?",
        [
            {
                "value": 640,
                "evidence_quote": "Budget is 640 units.",
                "assertion_kind": "asserted",
            }
        ],
    )
    assert not result.signals


async def test_a_question_fragment_in_a_mixed_message_is_not_an_assertion() -> None:
    result = await extract_signals(
        "Budget is 640 units. When will delivery arrive?",
        [
            {
                "value": "unknown",
                "evidence_quote": "delivery arrive",
                "assertion_kind": "asserted",
            },
            {
                "value": 640,
                "evidence_quote": "Budget is 640 units.",
                "assertion_kind": "asserted",
            },
        ],
    )
    assert [signal.value for signal in result.signals] == [640]


async def test_declared_hypotheticals_and_inferred_absence_are_not_facts() -> None:
    for kind in ("hypothetical", "inferred_absence"):
        result = await extract_signals(
            "Maybe the budget will change.",
            [
                {
                    "evidence_quote": "Maybe the budget will change.",
                    "assertion_kind": kind,
                }
            ],
        )
        assert not result.signals


def test_an_unproven_legacy_preference_is_not_assumed_global() -> None:
    session, episode = source("The workshop prefers a 640-unit budget.")
    signal = ExtractedSignal(
        concept="budget",
        value=640,
        context_type=ContextType.PREFERENCE,
        scope_cue=ScopeCue(scope_type=ScopeType.USER),
        source_episode_ids=(episode.episode_id,),
    )
    decision = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert (
        isinstance(decision, ScopeAssignment)
        and decision.scope_type == ScopeType.PROJECT
    )


def test_personal_applicability_survives_graph_roundtrip_without_rewriting_legacy_nodes() -> (
    None
):
    from context_graph.graph.mapping import context_from_node, context_properties
    from tests.factories import context_node

    personal = context_from_node({**context_node(), "personal_scope": True})
    assert (
        personal.personal_scope
        and context_properties(personal, None)["personal_scope"] is True
    )
    legacy = context_from_node(context_node())
    assert legacy.personal_scope is None


async def test_a_fresh_ace_proposal_cannot_omit_the_new_evidence_fields() -> None:
    result = await extract_signals("Tell me the project budget", [{}])
    assert not result.signals
    result = await extract_signals("The project budget is 640 units", [{"value": 640}])
    assert not result.signals  # Unsupported proposals are not silently accepted.


@pytest.mark.parametrize("state", ["unknown", "pending"])
async def test_explicit_user_uncertainty_is_not_an_inferred_absence(state: str) -> None:
    text = f"The delivery schedule is {state}."
    result = await extract_signals(
        text,
        [
            {
                "concept": "delivery_schedule",
                "value": state,
                "evidence_quote": text,
                "assertion_kind": "asserted",
            }
        ],
    )
    assert len(result.signals) == 1 and result.signals[0].value == state


async def test_question_episode_is_not_retained_as_support_for_another_episodes_assertion() -> (
    None
):
    actor = principal(projects=["alpha"])
    stream = Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="alpha")
    stream = append_event(
        stream,
        actor,
        event(project_id="alpha", text="What is the budget?"),
        max_events=16,
    )
    stream = append_event(
        stream,
        actor,
        event(2, project_id="alpha", text="The budget is 640 units."),
        max_events=16,
    )
    episodes = single_span_episodes(to_session(stream))
    batch = ExtractionBatch(
        run_id="proof",
        session_id=episodes[0].session_id,
        chunks=tuple(
            EpisodeChunk(
                episode=episode, char_end=len(episode.text), token_estimate=100
            )
            for episode in episodes
        ),
        token_estimate=200,
    )
    result = ExtractionEnvelope(
        signals=(
            ExtractedSignal(
                concept="budget",
                value=640,
                evidence_quote="The budget is 640 units.",
                assertion_kind="asserted",
                source_episode_ids=tuple(episode.episode_id for episode in episodes),
            ),
        )
    )
    actual = await service(FakeLLMProvider([result]), InMemoryLedger()).extract(batch)
    assert actual.signals[0].source_episode_ids == (episodes[1].episode_id,)


def test_an_unbound_nonpersonal_claim_is_not_widened_into_global_user_memory() -> None:
    from context_graph.pipeline.policy import UnresolvedSignal

    actor = principal()
    stream = append_event(
        Stream(tenant_id="t1", user_id="u1", session_id="s1"),
        actor,
        event(text="The event budget is 640 units."),
        max_events=16,
    )
    session = to_session(stream)
    episode = single_span_episodes(session)[0]
    signal = ExtractedSignal(
        concept="budget",
        value=640,
        scope_cue=ScopeCue(scope_type=ScopeType.USER),
        personal_scope=False,
        source_episode_ids=(episode.episode_id,),
    )
    result = WriterPolicy(PromotionSettings()).decide(signal, session, episode)
    assert isinstance(result, UnresolvedSignal)
