"""Adversarial source boundaries: project provenance and observation time."""

from datetime import timedelta

import pytest

from agent_context.assembly import ContextAssembler
from context_graph.domain.enums import ContextStatus
from tests.unit.test_assembly import ACTOR, NOW, Source, item, request
from tests.unit.test_context_search import query


@pytest.mark.parametrize("operation", ["assemble", "search"])
@pytest.mark.parametrize("project_id", ["p2", "revoked-project"])
async def test_user_memory_cannot_escape_explicit_source_project(
    operation: str, project_id: str
) -> None:
    """USER scope is not a grant to ignore explicit source-project provenance."""
    actor = ACTOR.model_copy(update={"projects": frozenset({"p1", "p2"})})
    source = Source(item("private-project-fact", project_id=project_id))
    assembler = ContextAssembler(source)
    if operation == "assemble":
        result = await assembler.assemble(actor, request(project_id="p1"), now=NOW)
    else:
        result = await assembler.search(actor, query(project_id="p1"), now=NOW)
    assert not result.items
    assert "private-project-fact" not in result.model_dump_json()


async def test_personal_and_matching_project_user_memory_remain_available() -> None:
    result = await ContextAssembler(
        Source(item("personal"), item("project-fact", project_id="p1"))
    ).assemble(ACTOR, request(project_id="p1"), now=NOW)
    assert {entry.item_id for entry in result.items} == {"personal", "project-fact"}


@pytest.mark.parametrize("operation", ["assemble", "search"])
async def test_future_observation_cannot_hide_the_current_value(operation: str) -> None:
    source = Source(
        item("current", canonical_key="budget", text="Budget: 100"),
        item(
            "future",
            canonical_key="budget",
            text="Budget: 200",
            observed_at=NOW + timedelta(days=1),
        ),
    )
    assembler = ContextAssembler(source)
    if operation == "assemble":
        result = await assembler.assemble(ACTOR, request(), now=NOW)
    else:
        result = await assembler.search(ACTOR, query(), now=NOW)
    assert [entry.item_id for entry in result.items] == ["current"]
    assert "unresolved_single_value_conflicts" not in result.warnings


@pytest.mark.parametrize("revoked_first", [False, True])
async def test_disagreeing_sources_cannot_resurrect_an_inactive_item(
    revoked_first: bool,
) -> None:
    active = item("same-id")
    revoked = active.model_copy(update={"status": ContextStatus.REVOKED})
    first, second = (revoked, active) if revoked_first else (active, revoked)
    assembler = ContextAssembler(Source(first), optional_sources=(Source(second),))
    with pytest.raises(RuntimeError, match="disagree"):
        await assembler.assemble(ACTOR, request(), now=NOW)


@pytest.mark.parametrize(
    "suffix",
    [
        "?X-Amz-Signature=private",
        "?X-Goog-Credential=private",
        "?AWSAccessKeyId=private",
        "?sig=private",
        "?client_secret=private",
        "?api-key=private",
        "#access_token=private",
        "?%58-Amz-Signature=private",
    ],
)
def test_search_sources_do_not_publish_signed_credentials(suffix: str) -> None:
    from pydantic import HttpUrl, ValidationError

    from agent_context.search import SearchResult

    with pytest.raises(ValidationError, match="credential"):
        SearchResult(
            title="Private link", url=HttpUrl("https://example.org/resource" + suffix),
            snippet="Search snippet", retrieved_at=NOW,
        )
