"""Owned directory and routing through actual API/SDK/Mongo; no paid providers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from hashlib import sha256

import httpx
import pytest

from agent_context.api import create_app
from agent_context.assembly import ContextAssembler
from agent_context.client import AgentContextClient
from agent_context.contracts import Permission, Principal
from agent_context.event_store import MongoEventStore
from agent_context.handoff import HandoffService
from agent_context.navigation import ProjectCreate, ProjectEdit
from agent_context.project_routing import ProjectProposal, ProjectResolver
from agent_context.project_store import ProjectStore
from agent_context.task_state import TaskStateService, TaskCandidateSource
from tests.fakes import FakeLLMProvider
from tests.integration.test_ace_handoff import handoffs as handoffs
from tests.unit.test_assembly import Source
from tests.unit.test_event_contracts import event, principal


@dataclass
class Environment:
    store: ProjectStore
    events: MongoEventStore
    user: AgentContextClient
    host: AgentContextClient
    stranger: AgentContextClient
    outsider: AgentContextClient
    readonly: AgentContextClient
    actor: Principal


@pytest.fixture
async def projects(
    handoffs: tuple[HandoffService, MongoEventStore, dict[str, str]],
) -> AsyncIterator[Environment]:
    snapshots, events, _ = handoffs
    store = ProjectStore(
        events.collection.database.client, events.collection.database.name
    )
    await store.ensure_indexes()
    actor = principal(projects=["p1"], permissions=frozenset(Permission))
    identities = [
        actor,
        principal(projects=["p1"], actor_kind="agent", actor_id="research-agent"),
        actor.model_copy(update={"user_id": "other", "actor_id": "other"}),
        principal(actor_kind="agent", actor_id="other-agent"),
        actor.model_copy(update={"permissions": frozenset({Permission.VIEW})}),
    ]

    async def ready() -> bool:
        return True

    bindings = {
        sha256((str(index) * 40).encode()).hexdigest(): identity
        for index, identity in enumerate(identities)
    }
    tasks = TaskStateService(snapshots, events)
    app = create_app(
        events=events,
        handoffs=snapshots,
        assembler=ContextAssembler(
            Source(), required_sources=(TaskCandidateSource(tasks),)
        ),
        auth_bindings=bindings,
        ready=ready,
        project_store=store,
        tasks=tasks,
    )
    clients = [
        AgentContextClient(
            base_url="http://test",
            bearer_token=str(index) * 40,
            transport=httpx.ASGITransport(app=app),
        )
        for index in range(len(identities))
    ]
    try:
        yield Environment(
            store,
            events,
            clients[0],
            clients[1],
            clients[2],
            clients[3],
            clients[4],
            actor,
        )
    finally:
        await asyncio.gather(*(client.aclose() for client in clients))


def creation(**changes: object) -> ProjectCreate:
    return ProjectCreate.model_validate(
        {
            "title": "Harbor archive",
            "source_text": "I am building Harbor archive for local records.",
            "name_quote": "Harbor archive",
            "description": "local records",
            "idempotency_key": "create-1",
            "expected_revision": 0,
            **changes,
        }
    )


async def test_owned_creation_delegates_only_to_configured_same_owner_host(
    projects: Environment,
) -> None:
    env = projects
    entry = await env.user.create_project(creation())
    assert entry.managed and entry.project_id.startswith("project-")
    assert (await env.user.projects()).revision == 1
    assert (
        entry in (await env.user.projects()).projects
        and entry in (await env.host.projects()).projects
    )
    assert entry.project_id not in {
        item.project_id for item in (await env.stranger.projects()).projects
    }
    assert entry.project_id not in {
        item.project_id for item in (await env.outsider.projects()).projects
    }
    await env.user.record_events(event(project_id=entry.project_id))
    await env.host.record_events(
        event(
            2,
            project_id=entry.project_id,
            agent_id="research-agent",
            kind="assistant_message",
            text="Recorded answer",
        )
    )
    assert len((await env.user.session("s1")).events) == 2
    for client in (env.stranger, env.outsider):
        with pytest.raises(httpx.HTTPStatusError) as denied:
            await client.session("s1")
        assert denied.value.response.status_code in (403, 404)
    for client in (env.host, env.readonly):
        with pytest.raises(httpx.HTTPStatusError) as denied:
            await client.create_project(creation())
        assert denied.value.response.status_code == 403
    with pytest.raises(httpx.HTTPStatusError) as denied:
        await env.user.create_project(
            creation(idempotency_key="bad-agent", delegate_agent_id="unconfigured")
        )
    assert denied.value.response.status_code == 403


async def test_creation_idempotency_and_atomic_revision_prevent_duplicate_or_stale_writes(
    projects: Environment,
) -> None:
    env = projects
    results = await asyncio.gather(
        *(env.user.create_project(creation()) for _ in range(6))
    )
    assert len({item.project_id for item in results}) == 1
    assert len((await env.store.state(env.actor)).entries) == 1
    assert await env.user.create_project(creation(expected_revision=99)) == results[0]
    with pytest.raises(httpx.HTTPStatusError) as conflict:
        await env.user.create_project(
            creation(
                title="A second archive",
                name_quote="A second archive",
                source_text="A second archive",
                description="",
                idempotency_key="second",
            )
        )
    assert conflict.value.response.status_code == 409
    with pytest.raises(httpx.HTTPStatusError):
        await env.user.create_project(
            creation(
                source_text="An edited source contains Harbor archive for local records."
            )
        )


async def test_unicode_name_collision_and_rename_aliases_preserve_identity(
    projects: Environment,
) -> None:
    env = projects
    original = await env.user.create_project(creation())
    with pytest.raises(httpx.HTTPStatusError) as collision:
        await env.user.create_project(
            creation(
                title="ＨＡＲＢＯＲ archive",
                name_quote="ＨＡＲＢＯＲ archive",
                source_text="ＨＡＲＢＯＲ archive",
                description="",
                idempotency_key="duplicate",
                expected_revision=1,
            )
        )
    assert collision.value.response.status_code == 409
    renamed = await env.user.edit_project(
        original.project_id, ProjectEdit(title="Town archive", expected_version=1)
    )
    assert (
        renamed.project_id == original.project_id
        and "Harbor archive" in renamed.aliases
        and renamed.version == 2
    )
    with pytest.raises(httpx.HTTPStatusError):
        await env.user.edit_project(
            original.project_id, ProjectEdit(title="Stale name", expected_version=1)
        )
    with pytest.raises(httpx.HTTPStatusError):
        await env.stranger.edit_project(
            original.project_id, ProjectEdit(title="Hijacked", expected_version=2)
        )
    assert (await env.user.projects()).projects[-1].project_id == original.project_id


async def test_private_space_is_idempotent_and_quarantine_blocks_creation_and_navigation(
    projects: Environment,
) -> None:
    env = projects
    first = await env.user.personal_project()
    assert first.kind == "personal" and await env.user.personal_project() == first
    assert len((await env.store.state(env.actor)).entries) == 1
    await env.events.privacy.quarantine(env.actor)
    for operation in (
        env.user.projects(),
        env.user.personal_project(),
        env.user.create_project(creation()),
    ):
        with pytest.raises(httpx.HTTPStatusError) as denied:
            await operation
        assert denied.value.response.status_code == 403


async def test_natural_creation_then_new_chat_matches_existing_without_duplicate(
    projects: Environment,
) -> None:
    env = projects
    message = "I am building Harbor archive for local records."
    llm = FakeLLMProvider(
        [
            ProjectProposal(
                action="new",
                reference_quote=message,
                name_quote="Harbor archive",
                description_quote="local records",
                undertaking="active",
                confidence=0.99,
            )
        ]
    )
    first = await ProjectResolver(env.user, llm).resolve(
        message=message, request_id="first"
    )
    assert first.project
    resolver = ProjectResolver(
        env.user,
        FakeLLMProvider(
            [
                ProjectProposal(
                    action="existing",
                    project_ids=(first.project.project_id,),
                    reference_quote="the local history archive",
                    confidence=0.98,
                )
            ]
        ),
    )
    again = await resolver.resolve(
        message="Continue the local history archive", request_id="again"
    )
    assert again.project and again.project.project_id == first.project.project_id
    assert len((await env.store.state(env.actor)).entries) == 1
    assert await env.events.collection.count_documents({}) == 0


@pytest.mark.parametrize(
    "proposal",
    [
        ProjectProposal(
            action="new",
            reference_quote="a garden",
            name_quote="a garden",
            undertaking="hypothetical",
            confidence=0.99,
        ),
        ProjectProposal(
            action="existing",
            project_ids=("forged",),
            reference_quote="a garden",
            confidence=1,
        ),
        ProjectProposal(
            action="new",
            reference_quote="a garden",
            name_quote="Invented name",
            undertaking="active",
            confidence=1,
        ),
        ProjectProposal(
            action="new",
            reference_quote="a garden",
            name_quote="a garden",
            undertaking="active",
            confidence=0.7,
        ),
    ],
)
async def test_unsafe_routing_neither_creates_nor_records(
    projects: Environment, proposal: ProjectProposal
) -> None:
    env = projects
    result = await ProjectResolver(env.user, FakeLLMProvider([proposal])).resolve(
        message="What if we started a garden?", request_id="unsafe"
    )
    assert result.project is None and result.clarification
    assert not (await env.store.state(env.actor)).entries
    assert await env.events.collection.count_documents({}) == 0


async def test_concurrent_directory_change_refreshes_before_creating_again(
    projects: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = projects
    original_create = env.user.create_project

    async def changed(body: ProjectCreate):
        await original_create(body)
        raise httpx.HTTPStatusError(
            "lost response",
            request=httpx.Request("POST", "http://test"),
            response=httpx.Response(409),
        )

    monkeypatch.setattr(env.user, "create_project", changed)
    entry_id: list[str] = []

    def responder(payload: str, schema: type):
        import json

        directory = json.loads(payload)["directory"]
        managed = [row for row in directory if row["managed"]]
        if managed:
            entry_id.append(managed[0]["project_id"])
            return ProjectProposal(
                action="existing",
                project_ids=(managed[0]["project_id"],),
                reference_quote="Harbor archive",
                confidence=0.99,
            )
        return ProjectProposal(
            action="new",
            reference_quote="Harbor archive",
            name_quote="Harbor archive",
            undertaking="active",
            confidence=0.99,
        )

    result = await ProjectResolver(
        env.user, FakeLLMProvider(responder=responder)
    ).resolve(message="Build Harbor archive", request_id="race")
    assert result.project and result.project.project_id == entry_id[0]
    assert len((await env.store.state(env.actor)).entries) == 1


async def test_metadata_quotas_and_alias_conflicts_are_explicit_failures(
    projects: Environment,
) -> None:
    from agent_context.project_store import DirectoryState, StoredProject, MAX_PROJECTS

    env = projects
    initial = await env.user.create_project(creation())
    with pytest.raises(httpx.HTTPStatusError) as duplicate_alias:
        await env.user.edit_project(
            initial.project_id,
            ProjectEdit(
                title="Renamed archive",
                aliases=("Duplicate", "duplicate"),
                expected_version=1,
            ),
        )
    assert duplicate_alias.value.response.status_code == 422
    with pytest.raises(httpx.HTTPStatusError) as alias_limit:
        await env.user.edit_project(
            initial.project_id,
            ProjectEdit(
                title="Renamed archive",
                aliases=tuple("alias-" + str(i) for i in range(8)),
                expected_version=1,
            ),
        )
    assert alias_limit.value.response.status_code == 413
    state = await env.store.state(env.actor)
    filled = DirectoryState(
        revision=state.revision,
        entries=tuple(
            StoredProject(
                project_id=f"full-{i}",
                title=f"Project {i}",
                creation_key=f"key-{i}",
                creation_digest="test",
                managed=True,
            )
            for i in range(MAX_PROJECTS)
        ),
    )
    await env.store.collection.update_one(
        env.store.key(env.actor), {"$set": filled.model_dump(mode="json")}
    )
    with pytest.raises(httpx.HTTPStatusError) as full:
        await env.user.create_project(
            creation(idempotency_key="full", expected_revision=state.revision)
        )
    assert full.value.response.status_code == 413


@pytest.mark.parametrize(
    "changes",
    [
        {"idempotency_key": "ace-personal"},
        {
            "title": "Personal",
            "source_text": "Personal",
            "name_quote": "Personal",
            "description": "",
        },
    ],
)
async def test_reserved_personal_space_cannot_be_hijacked_by_project_creation(
    projects: Environment, changes: dict[str, object]
) -> None:
    with pytest.raises(httpx.HTTPStatusError) as denied:
        await projects.user.create_project(creation(**changes))
    assert denied.value.response.status_code == 422
    assert not (await projects.store.state(projects.actor)).entries


async def test_resolved_project_assembles_its_current_state_in_a_fresh_conversation(
    projects: Environment,
) -> None:
    from agent_context.assembly import AssembleRequest, TokenBudget
    from agent_context.continuity import PROJECT_TASK_ID
    from agent_context.task_state import TaskUpdate

    env = projects
    entry = await env.user.create_project(creation())
    await env.user.record_events(
        event(
            project_id=entry.project_id,
            event_id="seed",
            text="Budget is 500 units. Review the records.",
        )
    )
    claim = await env.events.claim(env.actor.tenant_id)
    assert claim and await env.events.finish(*claim, success=True)
    await env.user.update_task(
        TaskUpdate(
            project_id=entry.project_id,
            task_id=PROJECT_TASK_ID,
            source_session_id="s1",
            source_event_id="seed",
            goal="Prepare the archive",
            requirements=("Budget is 500 units",),
            pending=("Review the records",),
            expected_version=0,
            idempotency_key="seed",
        )
    )
    resolver = ProjectResolver(
        env.user,
        FakeLLMProvider(
            [
                ProjectProposal(
                    action="existing",
                    project_ids=(entry.project_id,),
                    reference_quote="the local archive",
                    confidence=1,
                )
            ]
        ),
    )
    route = await resolver.resolve(
        message="Continue the local archive", request_id="new-conversation"
    )
    assert route.project and route.project.project_id == entry.project_id
    bundle = await env.user.assemble_context(
        AssembleRequest(
            agent_id="research-agent",
            session_id="new-session",
            project_id=route.project.project_id,
            task_id=PROJECT_TASK_ID,
            task_version=1,
            query="What remains?",
            budget=TokenBudget(model_context_tokens=12000),
        )
    )
    assert (
        "Budget is 500 units" in bundle.rendered
        and "Review the records" in bundle.rendered
    )
    assert bundle.items[0].approved_task_state and bundle.items[0].evidence_ids
    assert len((await env.store.state(env.actor)).entries) == 1


async def test_general_space_conversation_does_not_invent_a_project_task(
    projects: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_context.continuity import WorkspaceAssistant
    from agent_context.demo import WorkspaceAnswer
    from agent_context.contracts import EventStatus

    env = projects
    personal = await env.user.personal_project()

    async def advance(
        self: AgentContextClient, event_id: str, *, timeout_seconds: float = 2
    ) -> EventStatus:
        while claim := await env.events.claim(env.actor.tenant_id):
            assert await env.events.finish(*claim, success=True)
        return (await env.user.session("general")).status()

    monkeypatch.setattr(AgentContextClient, "wait_available", advance)
    llm = FakeLLMProvider([WorkspaceAnswer(answer="How can I help?", citations=())])
    assistant = WorkspaceAssistant(
        user=env.user,
        host=env.host,
        llm=llm,
        project_id=personal.project_id,
        documents={},
        track_task=False,
    )
    result = await assistant.turn(
        session_id="general", turn_id="hello", message="Hello"
    )
    assert result.task is None and len(llm.calls) == 1
    assert len((await env.user.session("general")).events) == 2
    with pytest.raises(httpx.HTTPStatusError) as absent:
        await env.user.current_task(personal.project_id, "project-work")
    assert absent.value.response.status_code == 404


async def test_long_configured_identifiers_do_not_block_creating_a_new_owned_project(
    projects: Environment,
) -> None:
    actor = projects.actor.model_copy(
        update={"projects": frozenset({"legacy." + "x" * 121})}
    )
    created = await projects.store.create(actor, creation())
    assert created.title == "Harbor archive"
    assert len((await projects.store.state(actor)).entries) == 1


async def test_configured_project_goal_hint_and_renaming_preserve_its_identity(
    projects: Environment,
) -> None:
    from agent_context.task_state import TaskUpdate, TaskStateService
    from agent_context.contracts import PROJECT_TASK_ID

    env = projects
    await env.user.record_events(
        event(project_id="p1", event_id="original", text="Plan the Harbor workshop.")
    )
    await env.user.update_task(
        TaskUpdate(
            project_id="p1",
            task_id=PROJECT_TASK_ID,
            source_session_id="s1",
            source_event_id="original",
            goal="Plan the Harbor workshop",
            expected_version=0,
            idempotency_key="initial",
        )
    )
    directory = await env.user.projects()
    configured = next(entry for entry in directory.projects if entry.project_id == "p1")
    assert configured.task_goal == "Plan the Harbor workshop"
    llm = FakeLLMProvider(
        [
            ProjectProposal(
                action="existing",
                project_ids=("p1",),
                reference_quote="the Harbor workshop",
                confidence=1,
            )
        ]
    )
    route = await ProjectResolver(env.user, llm).resolve(
        message="Continue the Harbor workshop", request_id="resume"
    )
    assert route.project and route.project.project_id == "p1"
    assert "Plan the Harbor workshop" in llm.calls[0][1]
    renamed = await env.user.edit_project(
        "p1", ProjectEdit(title="Harbor workshop", expected_version=1)
    )
    assert renamed.project_id == "p1" and renamed.managed and "P1" in renamed.aliases
    assert (await env.user.session("s1")).project_id == "p1"
    assert (
        next(
            entry
            for entry in (await env.host.projects()).projects
            if entry.project_id == "p1"
        ).title
        == "Harbor workshop"
    )
    assert len((await env.store.state(env.actor)).entries) == 1
    await env.events.privacy.block(
        env.actor, TaskStateService.identifier(env.actor, "p1", PROJECT_TASK_ID) + ":1"
    )
    assert (
        next(
            entry
            for entry in (await env.user.projects()).projects
            if entry.project_id == "p1"
        ).task_goal
        is None
    )


async def test_explicit_new_project_confirmation_bypasses_uncertain_model_without_saving_a_message(
    projects: Environment, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ui import workspace as ui
    from agent_context.assembly import SearchResult
    from agent_context.navigation import SessionPage

    env = projects
    snapshot = ui.WorkspaceSnapshot(
        await env.user.projects(),
        "p1",
        "s1",
        SessionPage(sessions=()),
        None,
        (),
        SearchResult(
            items=(), snapshot_id="empty", candidate_window=20, window_full=False
        ),
        None,
    )
    pending = ui.PendingTurn(
        project_id="p1",
        session_id="s1",
        turn_id="confirmed-new",
        message="I am organizing Cedar Clay workshop",
        sequence=1,
    )

    def client(variable: str = "ACE_DEMO_USER_TOKEN") -> AgentContextClient:
        return env.user if variable == "ACE_DEMO_USER_TOKEN" else env.host

    def forbidden(**kwargs: object) -> None:
        raise AssertionError("explicit user confirmation does not need a model")

    monkeypatch.setattr(ui, "client", client)
    monkeypatch.setattr(ui, "ChatLLMProvider", forbidden)
    result = await ui.prepare(snapshot, pending, new_project_name="Cedar Clay")
    assert result.pending.routed and result.pending.manual
    assert result.snapshot.project_id != snapshot.project_id
    assert (await env.store.state(env.actor)).entries[0].title == "Cedar Clay"
    assert await env.events.collection.count_documents({}) == 0
