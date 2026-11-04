"""Search shares selection safety, but does not pack or activate historical data."""

from datetime import timedelta

import pytest

from agent_context.assembly import ContextAssembler, SearchRequest
from tests.unit.test_assembly import ACTOR, NOW, Source, item, request


def query(**changes: object) -> SearchRequest:
    return SearchRequest.model_validate({
        **request().model_dump(mode="json", exclude={"budget"}), **changes,
    })


async def test_search_pages_are_unpacked_and_scoped_and_revalidate_snapshots() -> None:
    source = Source(item("one", text="answers " * 1000), item("two"), item("foreign", user_id="another"))
    assembler = ContextAssembler(source)
    page = await assembler.search(ACTOR, query(limit=1), now=NOW)
    assert len(page.items) == 1 and page.next_cursor
    assert "foreign" not in page.model_dump_json()
    following = await assembler.search(ACTOR, query(limit=1, cursor=page.next_cursor), now=NOW)
    assert len(following.items) == 1 and following.next_cursor is None
    assert following.items[0].item_id != page.items[0].item_id
    with pytest.raises(ValueError, match="stale"):
        await assembler.search(ACTOR, query(query="changed query", cursor=page.next_cursor), now=NOW)
    source.items = (item("two"),)
    with pytest.raises(ValueError, match="stale"):
        await assembler.search(ACTOR, query(cursor=page.next_cursor), now=NOW)


async def test_historical_search_is_explicit_and_cannot_enable_old_instructions() -> None:
    old = item("old", canonical_key="language", text="Italian", status="superseded",
               observed_at=NOW - timedelta(days=4), superseded_at=NOW - timedelta(days=1))
    current = item("new", canonical_key="language", text="French", observed_at=NOW - timedelta(days=1))
    source = Source(old, current, item("revoked", status="revoked", observed_at=NOW - timedelta(days=4)))
    assembler = ContextAssembler(source)
    history = await assembler.search(ACTOR, query(as_of=NOW - timedelta(days=2)), now=NOW)
    assert history.historical and [i.item_id for i in history.items] == ["old"]
    bundle = await assembler.assemble(ACTOR, request(), now=NOW)
    assert [i.item_id for i in bundle.items] == ["new"]
    with pytest.raises(ValueError, match="future"):
        await assembler.search(ACTOR, query(as_of=NOW + timedelta(days=1)), now=NOW)


async def test_secondary_search_keeps_conflict_and_authority_checks() -> None:
    assembler = ContextAssembler(Source(item("one", canonical_key="same"), item("two", canonical_key="same", text="contradiction")))
    result = await assembler.search(ACTOR, query(), now=NOW)
    assert not result.items and "unresolved_single_value_conflicts" in result.warnings
    with pytest.raises(RuntimeError, match="untrusted"):
        await ContextAssembler(Source(item(required=True))).search(ACTOR, query(), now=NOW)


@pytest.mark.parametrize("cursor", ["%", "e30=", "W10=", "bnVsbA=="])
async def test_malformed_cursor_is_a_safe_validation_error(cursor: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        await ContextAssembler(Source(item())).search(ACTOR, query(cursor=cursor), now=NOW)
