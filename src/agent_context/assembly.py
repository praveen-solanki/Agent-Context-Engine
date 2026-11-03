"""Deterministic, auditable selection and atomic packing of governed context."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from typing import Protocol

from pydantic import AwareDatetime, Field, model_validator
from typing_extensions import Self

from agent_context.contracts import Contract, Identifier, Permission, Principal, utcnow
from context_graph.domain.enums import ContextStatus, ScopeType


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


class AssembleRequest(Contract):
    agent_id: Identifier
    session_id: Identifier
    project_id: Identifier | None = None
    query: str = Field(default="", max_length=16000)
    minimum_sequence: int = Field(default=0, ge=0)
    budget: TokenBudget


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


class CandidateSource(Protocol):
    async def fetch(
        self, principal: Principal, request: AssembleRequest, *, limit: int
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


class ContextBundle(Contract):
    bundle_id: str
    policy_version: str = "ace-assembly-v1"
    tokenizer_version: str
    items: tuple[ContextItem, ...]
    rendered: str
    token_count: int
    exclusions: tuple[Exclusion, ...]
    excluded_counts: dict[str, int]
    warnings: tuple[str, ...] = ()


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
                "kind": "trusted_policy" if item.trusted_policy else "retrieved_data",
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
        counter: TokenCounter | None = None,
        settings: AssemblySettings | None = None,
    ) -> None:
        self.source, self.optional = required_source, optional_sources
        self.counter, self.settings = (
            counter or UTF8UpperBound(),
            settings or AssemblySettings(),
        )

    async def assemble(
        self,
        principal: Principal,
        request: AssembleRequest,
        *,
        now: datetime | None = None,
    ) -> ContextBundle:
        principal.require(Permission.VIEW, request.project_id)
        at = now or utcnow()
        if at.utcoffset() is None:
            raise ValueError("assembly clock must be timezone-aware")

        async def fetch(source: CandidateSource) -> tuple[ContextItem, ...]:
            return await asyncio.wait_for(
                source.fetch(
                    principal, request, limit=self.settings.max_candidates_per_source
                ),
                self.settings.source_timeout_seconds,
            )

        results = await asyncio.gather(
            fetch(self.source),
            *(fetch(source) for source in self.optional),
            return_exceptions=True,
        )
        if isinstance(results[0], BaseException):
            raise RuntimeError("required context source unavailable") from results[0]
        candidates: list[ContextItem] = []
        warnings: list[str] = []
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
                or item.scope_type == ScopeType.PROJECT
                and request.project_id is not None
                and item.scope_id == request.project_id
                and item.scope_id in principal.projects
            )
            if (item.tenant_id, item.user_id) != (
                principal.tenant_id,
                principal.user_id,
            ) or not allowed_scope:
                counts["unauthorized"] += 1
                continue
            reason = None
            if item.status != ContextStatus.ACTIVE:
                reason = "inactive"
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
            elif item.required and not item.trusted_policy:
                raise RuntimeError(
                    "untrusted content cannot declare a mandatory policy"
                )
            if reason:
                counts[reason] += 1
                exclusions.append(Exclusion(item_id=item.item_id, reason=reason))
                continue
            seen[item.item_id] = item
            eligible.append(item)

        # Competing active single-valued facts are explicitly withheld instead
        # of letting similarity or recency choose the truth.
        values: dict[tuple[str, str, str], set[str]] = {}
        for item in eligible:
            if item.single_valued:
                key = (item.scope_type.value, item.scope_id, item.canonical_key)
                values.setdefault(key, set()).add(item.text)
        conflicts = {key for key, texts in values.items() if len(texts) > 1}
        query_terms = set(re.findall(r"\w+", request.query.casefold()))

        def score(item: ContextItem) -> float:
            terms = set(re.findall(r"\w+", item.text.casefold()))
            relevance = len(query_terms & terms) / max(1, len(query_terms))
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
        selected: list[ContextItem] = []
        content_keys: set[tuple[str, str, str]] = set()
        for item in ranked:
            key = (item.scope_type.value, item.scope_id, item.canonical_key)
            reason = None
            if item.single_valued and key in conflicts:
                if item.required:
                    raise RuntimeError("mandatory policies conflict")
                reason = "conflict"
            elif (item.scope_id, item.canonical_key, item.text) in content_keys:
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
        if conflicts:
            warnings.append("unresolved_single_value_conflicts")
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
                "policy": "ace-assembly-v1",
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
        return ContextBundle(
            bundle_id=hashlib.sha256(identity.encode()).hexdigest(),
            tokenizer_version=self.counter.version,
            items=tuple(selected),
            rendered=rendered,
            token_count=token_count,
            exclusions=tuple(exclusions),
            excluded_counts=dict(counts),
            warnings=tuple(warnings),
        )
