"""Reported Atlas/Cedar routing states, independent of provider availability."""

from __future__ import annotations

import json
from typing import cast

import pytest

from agent_context.client import AgentContextClient
from agent_context.contracts import Permission
from agent_context.navigation import ProjectDirectory, ProjectEntry
from agent_context.project_routing import ProjectProposal, ProjectResolver
from context_graph.errors import ExtractionValidationError
from tests.fakes import FakeLLMProvider


ATLAS = ProjectEntry(
    project_id="project-atlas", title="Atlas", aliases=("Atlas migration",),
    task_goal="Move Atlas customer records to the new database.",
)
CEDAR = ProjectEntry(
    project_id="project-cedar", title="Cedar", aliases=("Cedar launch",),
    task_goal="Launch Cedar's workshop booking website.",
)


class ReadOnlyDirectory:
    """Any allocation would fail: existing-project resolution must only read."""

    def __init__(self) -> None:
        self.reads = 0

    async def projects(self) -> ProjectDirectory:
        self.reads += 1
        return ProjectDirectory(
            projects=(ATLAS, CEDAR), permissions=frozenset(Permission),
        )


@pytest.mark.parametrize(
    "message,reference,project",
    [
        ("Continue Atlas. What is the next step?", "Atlas", ATLAS),
        ("Continue Cedar. What is left to do?", "Cedar", CEDAR),
        ("What did we decide for Atlas migration?", "Atlas migration", ATLAS),
        ("Show the status of Cedar launch.", "Cedar launch", CEDAR),
        ("Continue our workshop booking website.", "workshop booking website", CEDAR),
    ],
)
async def test_reported_named_project_and_goal_references_resolve(
    message: str, reference: str, project: ProjectEntry,
) -> None:
    client = ReadOnlyDirectory()
    llm = FakeLLMProvider([
        ProjectProposal(
            action="existing", project_ids=(project.project_id,),
            reference_quote=reference, confidence=0.98,
        ),
    ])
    route = await ProjectResolver(cast(AgentContextClient, client), llm).resolve(
        message=message, request_id="reported-routing-check",
    )
    assert route.project == project and route.clarification is None
    supplied = json.loads(llm.calls[0][1])
    assert supplied["current_project_id"] is None
    assert {entry["project_id"] for entry in supplied["directory"]} == {
        ATLAS.project_id, CEDAR.project_id,
    }
    assert supplied["directory"][1]["task_goal"] == CEDAR.task_goal
    assert client.reads == 1


async def test_explicit_other_project_overrides_bound_current_conversation() -> None:
    llm = FakeLLMProvider([
        ProjectProposal(
            action="existing", project_ids=(CEDAR.project_id,),
            reference_quote="Cedar", confidence=0.98,
        ),
    ])
    route = await ProjectResolver(
        cast(AgentContextClient, ReadOnlyDirectory()), llm,
    ).resolve(
        message="Continue Cedar", request_id="switch",
        current_project_id=ATLAS.project_id,
    )
    assert route.project == CEDAR


@pytest.mark.parametrize(
    "proposal",
    [
        ProjectProposal(
            action="existing", project_ids=(ATLAS.project_id,),
            reference_quote="Atlas", confidence=0.5,
        ),
        ProjectProposal(
            action="existing", project_ids=(ATLAS.project_id,),
            reference_quote="not in the message", confidence=1,
        ),
        ProjectProposal(
            action="existing", project_ids=("forged-project",),
            reference_quote="Atlas", confidence=1,
        ),
        ProjectProposal(
            action="clarify", project_ids=(ATLAS.project_id, CEDAR.project_id),
            confidence=1,
        ),
    ],
)
async def test_name_occurrence_does_not_override_failed_safety_guards(
    proposal: ProjectProposal,
) -> None:
    result = await ProjectResolver(
        cast(AgentContextClient, ReadOnlyDirectory()), FakeLLMProvider([proposal]),
    ).resolve(message="Continue Atlas", request_id="uncertain")
    assert result.project is None and result.clarification


async def test_provider_failure_is_not_misreported_as_a_successful_name_match() -> None:
    llm = FakeLLMProvider()
    with pytest.raises(ExtractionValidationError):
        await ProjectResolver(
            cast(AgentContextClient, ReadOnlyDirectory()), llm,
        ).resolve(message="Continue Atlas", request_id="provider-failure")
    assert len(llm.calls) == 1


async def test_two_named_projects_require_split_instead_of_matching_first_name() -> None:
    proposal = ProjectProposal(
        action="multiple", project_ids=(ATLAS.project_id, CEDAR.project_id),
        reference_quote="Atlas", confidence=1,
    )
    route = await ProjectResolver(
        cast(AgentContextClient, ReadOnlyDirectory()), FakeLLMProvider([proposal]),
    ).resolve(
        message="Atlas is blocked; Cedar is ready. Update both.", request_id="multiple",
    )
    assert route.project is None and not route.candidates
    assert route.clarification and "one project at a time" in route.clarification
