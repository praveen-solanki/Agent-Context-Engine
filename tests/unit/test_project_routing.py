"""Routing uncertainty and UI-adapter scope binding without external calls."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest

from agent_context.assembly import SearchResult
from agent_context.client import AgentContextClient
from agent_context.contracts import Permission, Stream
from agent_context.demo import ResearchAssistant
from agent_context.events import append_event
from agent_context.navigation import ProjectDirectory, ProjectEntry, SessionPage
from agent_context.project_routing import (
    ProjectProposal,
    ProjectResolver,
    RoutingSettings,
)
from context_graph.errors import ExtractionValidationError
from tests.fakes import FakeLLMProvider
from tests.unit.test_event_contracts import event, principal
from ui import workspace as service
from ui.workspace import PendingTurn, WorkspaceSnapshot


DIRECTORY = ProjectDirectory(
    projects=(
        ProjectEntry(project_id="p1", title="Archive"),
        ProjectEntry(project_id="p2", title="Garden"),
    ),
    permissions=frozenset(Permission),
)


class DirectoryClient:
    def __init__(self, directory: ProjectDirectory = DIRECTORY) -> None:
        self.directory = directory
        self.reads = 0
        self.personal_calls = 0

    async def projects(self) -> ProjectDirectory:
        self.reads += 1
        return self.directory

    async def personal_project(self, _agent_id: str) -> ProjectEntry:
        self.personal_calls += 1
        return ProjectEntry(
            project_id="personal", title="Personal", kind="personal", managed=True
        )

    async def aclose(self) -> None:
        pass


class CloseableLLM(FakeLLMProvider):
    async def aclose(self) -> None:
        pass


def snapshot(project: str = "p1", session: str = "s1") -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        DIRECTORY,
        project,
        session,
        SessionPage(sessions=()),
        None,
        (),
        SearchResult(
            items=(), snapshot_id="empty", candidate_window=20, window_full=False
        ),
        None,
    )


@pytest.mark.parametrize(
    "proposal",
    [
        ProjectProposal(
            action="existing",
            project_ids=("p1", "p2"),
            reference_quote="both projects",
            confidence=1,
        ),
        ProjectProposal(action="existing", project_ids=("p2",), confidence=1),
        ProjectProposal(
            action="existing",
            project_ids=("p2",),
            reference_quote="both projects",
            confidence=0.5,
        ),
        ProjectProposal(action="general", confidence=1, needs_context=True),
    ],
)
async def test_ambiguity_is_not_a_project_guess(proposal: ProjectProposal) -> None:
    user = DirectoryClient()
    result = await ProjectResolver(
        cast(AgentContextClient, user), FakeLLMProvider([proposal])
    ).resolve(message="Continue both projects", request_id="turn")
    assert result.project is None and result.clarification and not user.personal_calls


async def test_personal_chat_and_existing_followup_use_different_scope_rules() -> None:
    user = DirectoryClient()
    llm = FakeLLMProvider(
        [
            ProjectProposal(action="general", confidence=1),
            ProjectProposal(action="general", confidence=1),
        ]
    )
    resolver = ProjectResolver(cast(AgentContextClient, user), llm)
    unbound = await resolver.resolve(message="I like short answers", request_id="one")
    bound = await resolver.resolve(
        message="Thanks", request_id="two", current_project_id="p2"
    )
    assert unbound.project and unbound.project.kind == "personal"
    assert (
        bound.project and bound.project.project_id == "p2" and user.personal_calls == 1
    )


async def test_provider_failure_or_oversized_directory_never_falls_back_to_a_project() -> (
    None
):
    user = DirectoryClient()
    llm = FakeLLMProvider()
    with pytest.raises(ValueError, match="routing budget"):
        await ProjectResolver(
            cast(AgentContextClient, user),
            llm,
            settings=RoutingSettings(max_input_bytes=1000),
        ).resolve(message="Continue", request_id="turn")
    assert not llm.calls and not user.personal_calls
    with pytest.raises(ExtractionValidationError):
        await ProjectResolver(cast(AgentContextClient, user), llm).resolve(
            message="Continue", request_id="turn"
        )
    assert not user.personal_calls


async def test_prepare_changes_scope_before_any_send_and_freezes_it_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = DirectoryClient()
    llm = CloseableLLM(
        [
            ProjectProposal(
                action="existing",
                project_ids=("p2",),
                reference_quote="the garden",
                confidence=1,
            )
        ]
    )
    loads: list[tuple[str | None, str | None]] = []

    async def load(
        project_id: str | None = None, session_id: str | None = None
    ) -> WorkspaceSnapshot:
        loads.append((project_id, session_id))
        return snapshot(project_id or "p1", session_id or "s1")

    def client(_variable: str = "ACE_DEMO_USER_TOKEN") -> DirectoryClient:
        return user

    def provider(**_kwargs: object) -> CloseableLLM:
        return llm

    monkeypatch.setattr(service, "client", client)
    monkeypatch.setattr(service, "ChatLLMProvider", provider)
    monkeypatch.setattr(service, "load", load)
    pending = PendingTurn(
        project_id="p1",
        session_id="s1",
        turn_id="turn",
        message="Continue the garden",
        sequence=1,
    )
    result = await service.prepare(snapshot(), pending)
    assert (
        result.pending.routed
        and result.pending.project_id == "p2"
        and result.pending.sequence == 1
    )
    assert (
        result.pending.session_id.startswith("auto-")
        and result.snapshot.project_id == "p2"
    )
    assert json.loads(llm.calls[0][1])["current_project_id"] is None
    again = await service.prepare(result.snapshot, result.pending)
    assert again == result and len(llm.calls) == 1 and len(loads) == 1


async def test_manual_choice_and_recorded_request_never_run_the_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = DirectoryClient()

    def client(_variable: str = "ACE_DEMO_USER_TOKEN") -> DirectoryClient:
        return user

    def forbidden_provider(**_kwargs: object) -> CloseableLLM:
        raise AssertionError("no model call expected")

    monkeypatch.setattr(service, "client", client)
    monkeypatch.setattr(service, "ChatLLMProvider", forbidden_provider)
    pending = PendingTurn(
        project_id="p1",
        session_id="s1",
        turn_id="old",
        message="An explicit project message",
        sequence=1,
        manual=True,
    )
    result = await service.prepare(snapshot(), pending)
    assert result.pending.routed and result.pending.manual
    identifier = ResearchAssistant.event_identifier("s1", "old")
    stream = append_event(
        Stream(tenant_id="t1", user_id="u1", session_id="s1", project_id="p1"),
        principal(projects=["p1"]),
        event(project_id="p1", event_id=identifier, text=pending.message),
        max_events=32,
    )
    prior = await service.prepare(
        replace(snapshot(), stream=stream), pending.model_copy(update={"manual": False})
    )
    assert prior.pending.routed and prior.pending.project_id == "p1"


async def test_missing_host_access_fails_before_route_is_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = DirectoryClient()
    host = DirectoryClient(DIRECTORY.model_copy(update={"projects": ()}))
    monkeypatch.setattr(
        service,
        "client",
        lambda variable="ACE_DEMO_USER_TOKEN": (
            user if variable == "ACE_DEMO_USER_TOKEN" else host
        ),
    )
    pending = PendingTurn(
        project_id="p1",
        session_id="s1",
        turn_id="one",
        message="Keep working",
        sequence=1,
        manual=True,
    )
    with pytest.raises(PermissionError, match="host cannot access"):
        await service.prepare(snapshot(), pending)
    assert not pending.routed


async def test_multi_project_updates_require_rephrasing_not_a_wholesale_assignment() -> (
    None
):
    user = DirectoryClient()
    proposal = ProjectProposal(
        action="multiple",
        project_ids=("p1", "p2"),
        reference_quote="both",
        confidence=1,
    )
    result = await ProjectResolver(
        cast(AgentContextClient, user), FakeLLMProvider([proposal])
    ).resolve(
        message="Update both: one is ready, the other is blocked", request_id="many"
    )
    assert result.project is None and not result.candidates
    assert result.clarification and "one project at a time" in result.clarification


async def test_an_owner_with_no_projects_can_start_in_personal_space(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_context.assembly import SearchRequest

    class EmptyOwner(DirectoryClient):
        async def personal_project(
            self, _agent_id: str = "research-agent"
        ) -> ProjectEntry:
            entry = await super().personal_project(_agent_id)
            self.directory = self.directory.model_copy(update={"projects": (entry,)})
            return entry

        async def sessions(self, _project_id: str) -> SessionPage:
            return SessionPage(sessions=())

        async def session(self, _identifier: str) -> Stream:
            import httpx

            raise httpx.HTTPStatusError(
                "new",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(404),
            )

        async def search_context(self, _request: SearchRequest) -> SearchResult:
            return SearchResult(
                items=(), snapshot_id="new", candidate_window=20, window_full=False
            )

        async def current_task(self, _project_id: str, _task_id: str) -> None:
            import httpx

            raise httpx.HTTPStatusError(
                "new",
                request=httpx.Request("GET", "http://test"),
                response=httpx.Response(404),
            )

    user = EmptyOwner(DIRECTORY.model_copy(update={"projects": ()}))

    def client(_variable: str = "ACE_DEMO_USER_TOKEN") -> EmptyOwner:
        return user

    monkeypatch.setattr(service, "client", client)
    result = await service.load()
    assert (
        result.project_id == "personal"
        and user.personal_calls == 1
        and result.task is None
    )
    with pytest.raises(PermissionError):
        await service.load("forged-project")
    assert user.personal_calls == 1
