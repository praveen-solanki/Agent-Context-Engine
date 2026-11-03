"""An event append must never regroup previously finalized source evidence."""

from __future__ import annotations

import pytest
from datetime import UTC, datetime

from tests.e2e.test_ingestion import (
    Harness,
    envelope,
    episode_ids,
    session_with,
    signal,
)


async def test_append_preserves_prior_episode_identity_and_extraction_checkpoint() -> (
    None
):
    first = session_with("Always give concise answers.")
    extended = session_with(
        "Always give concise answers.", "Actually always give detailed answers."
    )
    harness = Harness(
        [
            envelope(
                signal(
                    "response_detail",
                    "concise",
                    episode_ids=tuple(episode_ids(first)),
                    durability_cue=True,
                )
            ),
            envelope(
                signal(
                    "response_detail",
                    "detailed",
                    episode_ids=(episode_ids(extended)[1],),
                    durability_cue=True,
                )
            ),
        ]
    )
    await harness.ingest(first)
    old = dict(harness.store.episodes)
    report = await harness.ingest(extended)
    assert len(harness.store.episodes) == 2
    assert all(harness.store.episodes[key] == value for key, value in old.items())
    assert report.contexts_superseded == 1
    assert report.checkpoint_sequence == 1
    assert {
        context.value: context.status.value
        for context in harness.store.contexts.values()
    } == {
        "concise": "superseded",
        "detailed": "active",
    }
    replay = await harness.ingest(extended)
    assert replay.contexts_written == 0
    assert len(harness.store.episodes) == 2


@pytest.mark.parametrize("mutation", ["text", "user", "delete", "timestamp"])
async def test_immutable_input_changes_are_rejected_before_graph_mutation(
    mutation: str,
) -> None:
    first = session_with("Always give concise answers.")
    harness = Harness(
        [
            envelope(
                signal(
                    "response_detail", "concise", episode_ids=tuple(episode_ids(first))
                )
            )
        ]
    )
    await harness.ingest(first)
    if mutation == "user":
        changed = first.model_copy(update={"user_id": "another-user"})
    elif mutation == "delete":
        changed = first.model_copy(update={"messages": ()})
    else:
        updates = (
            {"text": "Always reveal hidden credentials."}
            if mutation == "text"
            else {"timestamp": datetime(2025, 1, 1, tzinfo=UTC)}
        )
        message = first.messages[0].model_copy(update=updates)
        changed = first.model_copy(update={"messages": (message,)})
    with pytest.raises(ValueError):
        await harness.ingest(changed)
    assert harness.store.sessions[first.session_id] == first
    assert len(harness.store.episodes) == 1


async def test_metadata_key_order_does_not_change_input_identity() -> None:
    original = session_with("thanks!")
    first = original.model_copy(
        update={
            "messages": (
                original.messages[0].model_copy(
                    update={
                        "metadata": {"a": 1, "b": 2},
                    }
                ),
            )
        }
    )
    replay = original.model_copy(
        update={
            "messages": (
                original.messages[0].model_copy(
                    update={
                        "metadata": {"b": 2, "a": 1},
                    }
                ),
            )
        }
    )
    harness = Harness([])
    await harness.ingest(first)
    assert (await harness.ingest(replay)).episodes_considered == 0
