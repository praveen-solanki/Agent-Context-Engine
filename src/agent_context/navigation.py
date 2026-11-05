"""Navigation contracts backed by the existing authenticated event store."""

from pydantic import AwareDatetime, Field

from agent_context.contracts import Contract, Identifier, Permission


class ProjectEntry(Contract):
    project_id: Identifier
    title: str


class ProjectDirectory(Contract):
    projects: tuple[ProjectEntry, ...]
    permissions: frozenset[Permission]


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
