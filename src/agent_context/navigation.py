"""Navigation contracts backed by the existing authenticated event store."""

from typing import Literal

from pydantic import AwareDatetime, Field, model_validator
from typing_extensions import Self

from agent_context.contracts import Contract, Identifier, Permission


class ProjectEntry(Contract):
    project_id: Identifier
    title: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    managed: bool = False
    kind: Literal["project", "personal"] = "project"
    version: int = 1
    task_goal: str | None = None


class ProjectDirectory(Contract):
    projects: tuple[ProjectEntry, ...]
    permissions: frozenset[Permission]
    revision: int = 0


class ProjectCreate(Contract):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    source_text: str = Field(min_length=1, max_length=4000)
    name_quote: str = Field(min_length=1, max_length=120)
    idempotency_key: Identifier
    expected_revision: int = Field(ge=0)
    delegate_agent_id: Identifier = "research-agent"

    @model_validator(mode="after")
    def sourced(self) -> Self:
        if not self.name_quote.strip() or self.name_quote not in self.source_text:
            raise ValueError("project creation needs an exact name quote")
        if self.description and self.description not in self.source_text:
            raise ValueError("project description needs an exact source quote")
        return self


class ProjectEdit(Contract):
    title: str = Field(min_length=1, max_length=120)
    aliases: tuple[str, ...] | None = Field(default=None, max_length=8)
    expected_version: int = Field(ge=1)


class SessionEntry(Contract):
    session_id: Identifier
    project_id: Identifier
    title: str
    updated_at: AwareDatetime | None = None


class SessionPage(Contract):
    sessions: tuple[SessionEntry, ...]
    next_cursor: str | None = None


class SessionTitle(Contract):
    title: str = Field(min_length=1, max_length=120)
