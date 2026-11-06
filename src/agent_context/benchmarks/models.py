"""Strict, secret-free experiment configuration and normalized benchmark records."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import AwareDatetime, Field, StrictBool, model_validator
from typing_extensions import Self

from agent_context.contracts import Contract, Identifier


class BenchmarkError(ValueError):
    """A safe, operator-facing benchmark configuration or data error."""


Method = Literal[
    "full_history",
    "last_n",
    "rolling_summary",
    "vector_top_k",
    "existing_retriever",
    "ace",
]
METHODS: tuple[Method, ...] = (
    "full_history",
    "last_n",
    "rolling_summary",
    "vector_top_k",
    "existing_retriever",
    "ace",
)


class Turn(Contract):
    id: str = Field(min_length=1)
    role: Literal["user", "assistant", "tool"]
    text: str = Field(min_length=1)
    timestamp: AwareDatetime


class Session(Contract):
    id: str = Field(min_length=1)
    turns: tuple[Turn, ...] = Field(min_length=1)


class Case(Contract):
    id: str = Field(min_length=1)
    subject_id: str | None = None
    category: str
    sessions: tuple[Session, ...] = Field(min_length=1)
    question: str = Field(min_length=1)
    answers: tuple[str, ...] = Field(min_length=1)
    question_time: AwareDatetime | None = None
    abstention: bool = False
    evidence_turns: tuple[str, ...] = ()
    evidence_sessions: tuple[str, ...] = ()
    synthetic_timestamps: bool = False
    context_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def identities(self) -> Self:
        if not self.question.strip() or any(
            not answer.strip() for answer in self.answers
        ):
            raise BenchmarkError("question and reference answers must be nonblank")
        sessions = [session.id for session in self.sessions]
        turns = [turn.id for session in self.sessions for turn in session.turns]
        if len(set(sessions)) != len(sessions) or len(set(turns)) != len(turns):
            raise BenchmarkError("session and turn IDs must be unique within a case")
        if not set(self.evidence_turns) <= set(turns) or not set(
            self.evidence_sessions
        ) <= set(sessions):
            raise BenchmarkError("gold evidence refers to an absent session/turn")
        stamps = [turn.timestamp for session in self.sessions for turn in session.turns]
        if stamps != sorted(stamps) or any(
            not turn.text.strip() for session in self.sessions for turn in session.turns
        ):
            raise BenchmarkError("history must be chronological with nonblank turns")
        if self.question_time and max(stamps) > self.question_time:
            raise BenchmarkError("history contains turns after the question date")
        return self


class Source(Contract):
    path: str
    local: Path | None = None
    url: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def origin(self) -> Self:
        if self.local and self.url:
            raise BenchmarkError("source must choose a local origin or a URL")
        if self.url:
            url = urlparse(self.url)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise BenchmarkError(
                    "source URLs must be HTTPS without credentials, query parameters or fragments"
                )
        return self


class HubSource(Contract):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pattern: str


class LocalSource(Contract):
    directory: Path
    pattern: str = "**/*.json"


class Dataset(Contract):
    id: Identifier
    format: Literal["longmemeval", "convomem", "locomo", "normalized"]
    revision: str = Field(min_length=1)
    split: str = Field(min_length=1)
    license: str = Field(min_length=1)
    sources: tuple[Source, ...] = ()
    hub: HubSource | None = None
    local: LocalSource | None = None
    categories: tuple[str, ...] = ()
    context_sizes: tuple[int, ...] = ()
    limit: int | None = Field(default=3, ge=1)
    missing_time_origin: AwareDatetime = datetime.fromisoformat(
        "2000-01-01T00:00:00+00:00"
    )

    @model_validator(mode="after")
    def acquisition(self) -> Self:
        if not self.sources and self.hub is None and self.local is None:
            raise BenchmarkError(
                "provide source files or a pinned Hugging Face repository"
            )
        if self.hub and self.revision in {"main", "master", "latest"}:
            raise BenchmarkError("hub revisions must be immutable commits")
        if (
            self.hub or any(source.url and not source.sha256 for source in self.sources)
        ) and not re.fullmatch(r"[a-f0-9]{40,64}", self.revision):
            raise BenchmarkError(
                "remote acquisition requires a full immutable commit digest"
            )
        return self


class Pricing(Contract):
    input_per_million_usd: float = Field(ge=0, allow_inf_nan=False)
    output_per_million_usd: float = Field(default=0, ge=0, allow_inf_nan=False)


class Experiment(Contract):
    schema_version: Literal[1] = 1
    name: Identifier
    datasets: tuple[Dataset, ...] = Field(min_length=1)
    artifacts: Path = Path("data/benchmarks")
    methods: tuple[Method, ...] = METHODS
    trials: int = Field(default=1, ge=1, le=100)
    seed: int = Field(default=0, ge=0, le=2**31 - 101)
    context_bytes: int = Field(default=4000, ge=128, le=1000000)
    max_output_tokens: int = Field(default=512, ge=32, le=16000)
    last_n: int = Field(default=3, ge=1)
    top_k: int = Field(default=3, ge=1)
    summary_input_bytes: int = Field(default=20000, ge=512, le=1000000)
    scoring: Literal["lexical", "judge"] = "lexical"
    time_mode: Literal["dataset", "wall"] = "dataset"
    answer_model: str | None = None
    ingestion_model: str | None = None
    judge_model: str | None = None
    prices: dict[str, Pricing] = Field(default_factory=dict)
    max_provider_requests: int = Field(default=200, ge=1)
    max_source_bytes: int = Field(default=4000000000, ge=1)
    max_record_bytes: int = Field(default=64000000, ge=1024)
    max_source_files: int = Field(default=10000, ge=1)
    # Reset is limited to stores claimed while empty by this benchmark process.
    exclusive_scratch_stores: bool = False
    ingestion_timeout_seconds: float = Field(default=90, gt=0, lt=3600)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len(set(self.methods)) != len(self.methods) or not self.methods:
            raise BenchmarkError("methods must be nonempty and unique")
        if len({d.id for d in self.datasets}) != len(self.datasets):
            raise BenchmarkError("dataset IDs must be unique")
        return self


class ContextView(Contract):
    text: str
    source_turns: tuple[str, ...] | None = None
    source_sessions: tuple[str, ...] | None = None


class Answer(Contract):
    answer: str = Field(max_length=64000)
    abstained: StrictBool = False


class JudgeDecision(Contract):
    correct: StrictBool
    rationale: str = Field(max_length=2000)


class Usage(Contract):
    model: str
    attempts: int = 0
    failed_attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    unreported: int = 0


class Measurement(Contract):
    seconds: float
    usage: dict[str, Usage]
    known_cost_usd: float | None


class PreparedManifest(Contract):
    schema_version: Literal[1] = 1
    dataset: Dataset
    cases: int
    cases_sha256: str
    sources: tuple[Source, ...]
    adapter_version: Literal["ace-datasets-v1"] = "ace-datasets-v1"
