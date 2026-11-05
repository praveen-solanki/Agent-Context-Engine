"""Deterministic, auditable selection and atomic packing of governed context."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, Literal

from pydantic import AwareDatetime, Field, model_validator
from typing_extensions import Self

from agent_context.contracts import Contract, Identifier, Permission, Principal, utcnow
from agent_context.events import EventConflict
from context_graph.domain.enums import ContextStatus, ScopeType

ASSEMBLY_POLICY_VERSION = "ace-assembly-v4"


def lexical_terms(text: str) -> set[str]:
    """Treat snake_case concept keys and natural-language words consistently."""
    return set(re.findall(r"[^\W_]+", text.casefold()))


class TokenBudget(Contract):
    model_context_tokens: int = Field(gt=0)
    reserved_instructions_tokens: int = Field(default=0, ge=0)
    reserved_tools_tokens: int = Field(default=0, ge=0)
    reserved_output_tokens: int = Field(default=0, ge=0)
    reserved_request_tokens: int = Field(default=0, ge=0)
    safety_margin_tokens: int = Field(default=64, ge=0)
    max_engine_tokens: int = Field(default=6000, ge=0)

    @property
    def available(self) -> int:
        remaining = self.model_context_tokens - sum(
            (
                self.reserved_instructions_tokens,
                self.reserved_tools_tokens,
                self.reserved_output_tokens,
                self.reserved_request_tokens,
                self.safety_margin_tokens,
            )
        )
        return max(0, min(self.max_engine_tokens, remaining))

    @model_validator(mode="after")
    def valid_reserves(self) -> Self:
        if (
            sum(
                (
                    self.reserved_instructions_tokens,
                    self.reserved_tools_tokens,
                    self.reserved_output_tokens,
                    self.reserved_request_tokens,
                    self.safety_margin_tokens,
                )
            )
            > self.model_context_tokens
        ):
            raise ValueError("host reserves exceed the model context window")
        return self


class ContextQuery(Contract):
    agent_id: Identifier
    session_id: Identifier
    project_id: Identifier | None = None
    task_id: Identifier | None = None
    task_version: int | None = Field(default=None, ge=1)
    query: str = Field(default="", max_length=16000)
    minimum_sequence: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def bound_task(self) -> Self:
        if self.task_id is not None and self.project_id is None:
            raise ValueError("a task must be bound to an authorized project")
        if self.task_version is not None and self.task_id is None:
            raise ValueError("a task version requires a task ID")
        return self


class AssembleRequest(ContextQuery):
    budget: TokenBudget


class SearchRequest(ContextQuery):
    """Progressive disclosure, never an instruction/assembly request.

    as_of is effective/event time, not a reconstruction of what the database
    knew at that time. Revocation and privacy fences always apply at read time.
    """

    as_of: AwareDatetime | None = None
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=512)


ContextWarning = Literal["completed_action_no_longer_verifiable", "artifact_version_changed"]


class ContextItem(Contract):
    item_id: str
    tenant_id: Identifier
    user_id: Identifier
    scope_type: ScopeType = ScopeType.USER
    scope_id: str
    canonical_key: str
    text: str = Field(max_length=64000)
    value: str | float | bool | None = None
    fingerprint: str | None = None
    evidence_ids: tuple[str, ...] = ()
    status: ContextStatus = ContextStatus.ACTIVE
    valid_from: AwareDatetime | None = None
    valid_until: AwareDatetime | None = None
    observed_at: AwareDatetime
    single_valued: bool = True
    required: bool = False
    trusted_policy: bool = False
    priority: float = Field(default=0, ge=0, le=1)
    semantic_score: float = Field(default=0, ge=0, le=1)
    superseded_at: AwareDatetime | None = None
    unresolved_conflict: bool = False
    approved_task_state: bool = False
    project_id: Identifier | None = None
    source_warnings: tuple[ContextWarning, ...] = ()


class CandidateSource(Protocol):
    async def fetch(
        self, principal: Principal, request: ContextQuery, *, limit: int
    ) -> tuple[ContextItem, ...]: ...


class TokenCounter(Protocol):
    @property
    def version(self) -> str: ...

    def count(self, text: str) -> int: ...


class UTF8UpperBound:
    """Conservative byte-level tokenizer bound; not measured provider usage."""

    version = "utf8-byte-bound-v1"

    def count(self, text: str) -> int:
        return len(text.encode("utf-8"))


class AssemblySettings(Contract):
    max_candidates_per_source: int = Field(default=256, ge=1, le=4096)
    source_timeout_seconds: float = Field(default=5, gt=0, le=60)
    relevance_weight: float = Field(default=4, ge=0)
    priority_weight: float = Field(default=2, ge=0)
    recency_weight: float = Field(default=1, ge=0)
    recency_half_life_days: float = Field(default=30, gt=0)


class Exclusion(Contract):
    item_id: str
    reason: str


class AssemblyScope(Contract):
    tenant_id: Identifier
    user_id: Identifier
    actor_id: Identifier
    session_id: Identifier
    project_id: Identifier | None = None
    task_id: Identifier | None = None


SelectionReason = Literal[
    "mandatory_policy", "current_task_state", "lexical_relevance",
    "semantic_relevance", "standing_priority", "valid_recent_context",
]


class Selection(Contract):
    item_id: str
    reasons: tuple[SelectionReason, ...]


class ContextBundle(Contract):
    bundle_id: str
    policy_version: str = ASSEMBLY_POLICY_VERSION
    tokenizer_version: str
    items: tuple[ContextItem, ...]
    rendered: str
    token_count: int
    exclusions: tuple[Exclusion, ...]
    excluded_counts: dict[str, int]
    warnings: tuple[str, ...] = ()
    selections: tuple[Selection, ...] = ()
    scope: AssemblyScope | None = None
    consistency_sequence: int | None = None


class SearchResult(Contract):
    items: tuple[ContextItem, ...]
    next_cursor: str | None = None
    snapshot_id: str
    candidate_window: int
    window_full: bool
    historical: bool = False
    as_of: AwareDatetime | None = None
    warnings: tuple[str, ...] = ()
    consistency_sequence: int | None = None


class MandatoryContextTooLarge(ValueError):
    """Fail closed instead of silently removing a mandatory instruction."""


def render(items: list[ContextItem]) -> str:
    """JSON escapes delimiters; data cannot manufacture another bundle section.

    Host integrations must keep retrieved_data in a data/tool message, never
    concatenate it into the host system/developer instruction channel.
    """
    if not items:
        return ""
    return json.dumps(
        [
            {
                "kind": (
                    "trusted_policy" if item.trusted_policy
                    else "current_task_state" if item.approved_task_state
                    else "retrieved_data"
                ),
                "id": item.item_id,
                "text": item.text,
                "evidence": item.evidence_ids,
            }
            for item in items
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


class ContextAssembler:
    def __init__(
        self,
        required_source: CandidateSource,
        *,
        optional_sources: tuple[CandidateSource, ...] = (),
        required_sources: tuple[CandidateSource, ...] = (),
        counter: TokenCounter | None = None,
        settings: AssemblySettings | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.source, self.optional = required_source, optional_sources
        self.required = required_sources
        self.clock = clock
        self.counter, self.settings = (
            counter or UTF8UpperBound(),
            settings or AssemblySettings(),
        )

    async def _rank(
        self,
        principal: Principal,
        request: ContextQuery,
        *,
        now: datetime | None = None,
    ) -> tuple[list[ContextItem], list[Exclusion], Counter[str], list[str], bool]:
        principal.require(Permission.VIEW, request.project_id)
        clock = now or self.clock()
        historical = isinstance(request, SearchRequest) and request.as_of is not None
        at = (
            request.as_of
            if isinstance(request, SearchRequest) and request.as_of
            else clock
        )
        if at.utcoffset() is None:
            raise ValueError("assembly clock must be timezone-aware")
        if historical and at > clock:
            raise ValueError("historical search cannot request a future instant")

        async def fetch(source: CandidateSource) -> tuple[ContextItem, ...]:
            return await asyncio.wait_for(
                source.fetch(
                    principal, request, limit=self.settings.max_candidates_per_source
                ),
                self.settings.source_timeout_seconds,
            )

        results = await asyncio.gather(
            fetch(self.source),
            *(fetch(source) for source in self.required),
            *(fetch(source) for source in self.optional),
            return_exceptions=True,
        )
        for result in results[:1 + len(self.required)]:
            if isinstance(result, (LookupError, PermissionError, EventConflict)):
                raise result
            if isinstance(result, BaseException):
                raise RuntimeError("required context source unavailable") from result
        candidates: list[ContextItem] = []
        warnings: list[str] = []
        if historical and request.task_id is not None:
            warnings.append("historical_task_state_not_included")
        for index, result in enumerate(results):
            if isinstance(result, BaseException):
                warnings.append(f"optional_source_{index}_unavailable")
            else:
                if len(result) > self.settings.max_candidates_per_source:
                    raise RuntimeError("candidate source exceeded its bounded contract")
                candidates.extend(result)
        exclusions: list[Exclusion] = []
        counts: Counter[str] = Counter()
        eligible: list[ContextItem] = []
        seen: dict[str, ContextItem] = {}
        for item in candidates:
            # Unauthorized IDs are never emitted in a trace. Filtering here is
            # defensive; each source must constrain its underlying data query.
            allowed_scope = (
                item.scope_type == ScopeType.USER
                and item.scope_id == principal.user_id
                or item.scope_type == ScopeType.SESSION
                and item.scope_id == request.session_id
                and (
                    item.project_id is None
                    or (
                        item.project_id == request.project_id
                        and item.project_id in principal.projects
                    )
                )
                or item.scope_type == ScopeType.PROJECT
                and request.project_id is not None
                and item.scope_id == request.project_id
                and item.scope_id in principal.projects
                or item.scope_type == ScopeType.TASK
                and request.task_id is not None
                and item.scope_id == request.task_id
                and item.project_id == request.project_id
                and item.project_id in principal.projects
            )
            if (item.tenant_id, item.user_id) != (
                principal.tenant_id,
                principal.user_id,
            ) or not allowed_scope:
                counts["unauthorized"] += 1
                continue
            reason = None
            if item.status != ContextStatus.ACTIVE and not (
                historical
                and item.status == ContextStatus.SUPERSEDED
                and item.superseded_at is not None
                and item.superseded_at > at
            ):
                reason = "inactive"
            elif historical and item.observed_at > at:
                reason = "not_yet_observed"
            elif item.superseded_at is not None and item.superseded_at <= at:
                reason = "superseded"
            elif (item.valid_from and item.valid_from > at) or (
                item.valid_until and item.valid_until <= at
            ):
                reason = "outside_validity"
            elif item.item_id in seen:
                if seen[item.item_id] != item:
                    raise RuntimeError(
                        "candidate sources disagree about an immutable item ID"
                    )
                reason = "duplicate"
            elif item.required and not (item.trusted_policy or item.approved_task_state):
                raise RuntimeError(
                    "untrusted content cannot declare a mandatory policy"
                )
            if reason:
                counts[reason] += 1
                exclusions.append(Exclusion(item_id=item.item_id, reason=reason))
                continue
            seen[item.item_id] = item
            eligible.append(item)
            warnings.extend(item.source_warnings)

        # Competing active single-valued facts are explicitly withheld instead
        # of letting similarity or recency choose the truth.
        values: dict[tuple[str, str, str], set[str]] = {}
        for item in eligible:
            if item.single_valued:
                key = (item.scope_type.value, item.scope_id, item.canonical_key)
                values.setdefault(key, set()).add(item.text)
        conflicts = {key for key, texts in values.items() if len(texts) > 1} | {
            (item.scope_type.value, item.scope_id, item.canonical_key)
            for item in eligible
            if item.single_valued and item.unresolved_conflict
        }
        query_terms = lexical_terms(request.query)

        def score(item: ContextItem) -> float:
            terms = lexical_terms(item.text)
            relevance = max(
                len(query_terms & terms) / max(1, len(query_terms)), item.semantic_score
            )
            age_days = max(0, (at - item.observed_at).total_seconds()) / 86400
            return (
                relevance * self.settings.relevance_weight
                + item.priority * self.settings.priority_weight
                + 2 ** (-age_days / self.settings.recency_half_life_days)
                * self.settings.recency_weight
            )

        ranked = sorted(
            eligible, key=lambda item: (not item.required, -score(item), item.item_id)
        )
        if conflicts:
            warnings.append("unresolved_single_value_conflicts")
        unambiguous: list[ContextItem] = []
        for item in ranked:
            key = (item.scope_type.value, item.scope_id, item.canonical_key)
            if item.single_valued and key in conflicts:
                if item.required:
                    raise RuntimeError("mandatory policies conflict")
                counts["conflict"] += 1
                exclusions.append(Exclusion(item_id=item.item_id, reason="conflict"))
            else:
                unambiguous.append(item)
        return unambiguous, exclusions, counts, warnings, any(
            not isinstance(result, BaseException)
            and len(result) == self.settings.max_candidates_per_source
            for result in results
        )

    async def search(
        self, principal: Principal, request: SearchRequest, *, now: datetime | None = None
    ) -> SearchResult:
        ranked, _, _, warnings, window_full = await self._rank(
            principal, request, now=now
        )
        # A cursor is a position, never an authorization grant. Every page
        # reruns live scoped retrieval/privacy checks. Changed results fail
        # explicitly rather than silently skipping or repeating candidates.
        principal_data = principal.model_dump(mode="json")
        principal_data["projects"] = sorted(principal.projects)
        principal_data["permissions"] = sorted(principal.permissions)
        identity = {
            "principal": principal_data,
            "query": request.model_dump(mode="json", exclude={"limit", "cursor"}),
            "items": [item.model_dump(mode="json") for item in ranked],
        }
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        offset = 0
        if request.cursor:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(request.cursor))
                offset = cursor["offset"]
                if (
                    cursor["snapshot"] != digest
                    or type(offset) is not int
                    or not 0 < offset < len(ranked)
                ):
                    raise ValueError("search snapshot changed; restart search")
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError("invalid or stale search cursor; restart search") from error
        end = offset + request.limit
        following = (
            base64.urlsafe_b64encode(
                json.dumps({"offset": end, "snapshot": digest}).encode()
            ).decode()
            if end < len(ranked)
            else None
        )
        return SearchResult(
            items=tuple(ranked[offset:end]),
            next_cursor=following,
            snapshot_id=digest,
            candidate_window=self.settings.max_candidates_per_source,
            window_full=window_full,
            historical=request.as_of is not None,
            as_of=request.as_of,
            warnings=tuple(warnings),
        )

    async def assemble(
        self, principal: Principal, request: AssembleRequest, *, now: datetime | None = None
    ) -> ContextBundle:
        ranked, exclusions, counts, warnings, _ = await self._rank(
            principal, request, now=now
        )
        selected: list[ContextItem] = []
        content_keys: set[tuple[str, str, str]] = set()
        for item in ranked:
            reason = None
            if (item.scope_id, item.canonical_key, item.text) in content_keys:
                reason = "duplicate"
            elif (
                self.counter.count(render([*selected, item])) > request.budget.available
            ):
                if item.required:
                    raise MandatoryContextTooLarge(
                        "mandatory context exceeds the allocated budget"
                    )
                reason = "budget"
            if reason:
                counts[reason] += 1
                exclusions.append(Exclusion(item_id=item.item_id, reason=reason))
            else:
                selected.append(item)
                content_keys.add((item.scope_id, item.canonical_key, item.text))
        rendered = render(selected)
        token_count = self.counter.count(rendered)
        principal_data = principal.model_dump(mode="json")
        principal_data["projects"] = sorted(principal.projects)
        principal_data["permissions"] = sorted(principal.permissions)
        identity = json.dumps(
            {
                "principal": principal_data,
                "request": request.model_dump(mode="json"),
                "items": [i.model_dump(mode="json") for i in selected],
                "policy": ASSEMBLY_POLICY_VERSION,
                "tokenizer": self.counter.version,
                "rendered": rendered,
                "settings": self.settings.model_dump(),
                "warnings": warnings,
                "exclusions": [e.model_dump() for e in exclusions],
                "counts": dict(counts),
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        def selection(item: ContextItem) -> Selection:
            reasons: list[SelectionReason] = ["valid_recent_context"]
            if item.required and item.trusted_policy:
                reasons.append("mandatory_policy")
            if item.approved_task_state:
                reasons.append("current_task_state")
            if lexical_terms(request.query) & lexical_terms(item.text):
                reasons.append("lexical_relevance")
            if item.semantic_score > 0:
                reasons.append("semantic_relevance")
            if item.priority > 0:
                reasons.append("standing_priority")
            return Selection(item_id=item.item_id, reasons=tuple(reasons))

        return ContextBundle(
            bundle_id=hashlib.sha256(identity.encode()).hexdigest(),
            tokenizer_version=self.counter.version,
            items=tuple(selected),
            rendered=rendered,
            token_count=token_count,
            exclusions=tuple(exclusions),
            excluded_counts=dict(counts),
            warnings=tuple(warnings),
            scope=AssemblyScope(
                tenant_id=principal.tenant_id, user_id=principal.user_id,
                actor_id=principal.actor_id, session_id=request.session_id,
                project_id=request.project_id, task_id=request.task_id,
            ),
            selections=tuple(selection(item) for item in selected),
        )
