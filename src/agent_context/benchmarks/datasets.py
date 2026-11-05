"""Pinned acquisition and label-preserving adapters; no model calls."""

from __future__ import annotations

import fnmatch
import heapq
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from agent_context.benchmarks.models import (
    BenchmarkError,
    Case,
    Dataset,
    Experiment,
    PreparedManifest,
    Session,
    Source,
    Turn,
)
from agent_context.benchmarks.storage import atomic_write, digest, fingerprint, records


def acquisition_fingerprint(dataset: Dataset) -> str:
    # Sampling/scoring changes must not invalidate immutable raw downloads.
    return fingerprint(
        dataset.model_dump(mode="json", include={"revision", "sources", "hub", "local"})
    )


def safe_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\" in name:
        raise BenchmarkError("dataset paths must stay within their root")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()):
        raise BenchmarkError("dataset path escapes its root")
    return target


async def discover(
    dataset: Dataset, client: httpx.AsyncClient, limit: int
) -> tuple[Source, ...]:
    if dataset.local is not None:
        files = sorted(dataset.local.directory.glob(dataset.local.pattern))
        files = [path for path in files if path.is_file()]
        if not files or len(files) > limit:
            raise BenchmarkError(
                "local dataset pattern is empty or exceeds the file limit"
            )
        return (
            *dataset.sources,
            *(
                Source(
                    path=str(path.relative_to(dataset.local.directory)),
                    local=path.resolve(),
                )
                for path in files
            ),
        )
    if dataset.hub is None:
        return dataset.sources
    repository = quote(dataset.hub.repository, safe="/")
    revision = quote(dataset.revision, safe="")
    url: str | None = (
        f"https://huggingface.co/api/datasets/{repository}/tree/{revision}?recursive=true&limit=1000"
    )
    sources: list[Source] = list(dataset.sources)
    visited: set[str] = set()
    while url:
        if url in visited or len(visited) >= 1000:
            raise BenchmarkError("cyclic or excessive dataset tree pagination")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "huggingface.co":
            raise BenchmarkError("unexpected dataset metadata pagination destination")
        visited.add(url)
        response = await client.get(url)
        response.raise_for_status()
        for entry in response.json():
            path = entry["path"]
            if entry.get("type") != "file" or not fnmatch.fnmatchcase(
                path, dataset.hub.pattern
            ):
                continue
            safe_path(Path("."), path)
            oid = (entry.get("lfs") or {}).get("oid", "")
            sources.append(
                Source(
                    path=path,
                    url=f"https://huggingface.co/datasets/{repository}/resolve/{revision}/{quote(path, safe='/')}",
                    sha256=oid if len(oid) == 64 else None,
                )
            )
            if len(sources) > limit:
                raise BenchmarkError(
                    "dataset file limit exceeded; narrow the configured pattern"
                )
        url = response.links.get("next", {}).get("url")
    if not sources:
        raise BenchmarkError("dataset pattern matched no source files")
    return tuple(sorted(sources, key=lambda source: source.path))


async def acquire(
    dataset: Dataset,
    config: Experiment,
    root: Path,
    *,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """Reuse only checksum-verified cache; publish the lock after all files pass."""
    directory = root / "raw" / dataset.id
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = directory / "sources.lock.json"
    previous = json.loads(lock.read_text()) if lock.exists() else None
    if previous and previous["dataset_sha256"] != acquisition_fingerprint(dataset):
        raise BenchmarkError(
            "dataset configuration changed; use a new dataset ID/cache directory"
        )
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=120, follow_redirects=True)
    try:
        sources = (
            tuple(Source.model_validate(row) for row in previous["sources"])
            if previous
            else await discover(dataset, client, config.max_source_files)
        )
        if len(sources) > config.max_source_files:
            raise BenchmarkError("dataset file limit exceeded")
        locked: list[Source] = []
        for source in sources:
            target = safe_path(directory, source.path)
            origin = target.with_name(target.name + ".origin.json")
            if target.exists():
                if target.stat().st_size > config.max_source_bytes:
                    raise BenchmarkError("cached source exceeds byte limit")
                actual = digest(target)
                if source.sha256 and source.sha256 != actual:
                    raise BenchmarkError("cached dataset checksum mismatch")
                if source.url and not source.sha256:
                    checkpoint = (
                        json.loads(origin.read_text()) if origin.exists() else {}
                    )
                    if (
                        checkpoint.get("dataset_sha256")
                        != acquisition_fingerprint(dataset)
                        or checkpoint.get("url") != source.url
                        or checkpoint.get("sha256") != actual
                    ):
                        raise BenchmarkError(
                            "unlocked remote cache; remove it and reacquire"
                        )
            elif source.local:
                if (
                    not source.local.is_file()
                    or source.local.stat().st_size > config.max_source_bytes
                ):
                    raise BenchmarkError(
                        "local source is missing or exceeds the byte limit"
                    )
                actual = digest(source.local)
                if source.sha256 and source.sha256 != actual:
                    raise BenchmarkError("local dataset checksum mismatch")
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(dir=target.parent)
                os.close(fd)
                try:
                    shutil.copyfile(source.local, temporary)
                    if digest(Path(temporary)) != actual:
                        raise BenchmarkError("local source changed during acquisition")
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            elif source.url:
                parsed = urlparse(source.url)
                if (
                    parsed.scheme != "https"
                    or parsed.username
                    or parsed.password
                    or not parsed.hostname
                ):
                    raise BenchmarkError(
                        "dataset URLs must use HTTPS without embedded credentials"
                    )
                if source.sha256 is None and (
                    dataset.revision in {"main", "master", "latest"}
                    or dataset.revision not in source.url
                ):
                    raise BenchmarkError(
                        "remote URL must contain its immutable dataset revision"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                fd, temporary = tempfile.mkstemp(dir=target.parent)
                try:
                    with os.fdopen(fd, "wb") as output:
                        count = 0
                        async with client.stream("GET", source.url) as response:
                            response.raise_for_status()
                            async for block in response.aiter_bytes():
                                count += len(block)
                                if count > config.max_source_bytes:
                                    raise BenchmarkError(
                                        "download exceeds source byte limit"
                                    )
                                output.write(block)
                    actual = digest(Path(temporary))
                    if source.sha256 and source.sha256 != actual:
                        raise BenchmarkError("downloaded dataset checksum mismatch")
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            else:
                raise FileNotFoundError(
                    f"local dataset source is missing: {source.path}"
                )
            locked.append(source.model_copy(update={"sha256": actual}))
            if source.url:
                atomic_write(
                    origin,
                    json.dumps(
                        {
                            "dataset_sha256": acquisition_fingerprint(dataset),
                            "url": source.url,
                            "sha256": actual,
                        }
                    )
                    + "\n",
                )
        atomic_write(
            lock,
            json.dumps(
                {
                    "dataset_sha256": acquisition_fingerprint(dataset),
                    "sources": [source.model_dump(mode="json") for source in locked],
                },
                indent=2,
            )
            + "\n",
        )
        return lock
    finally:
        if owns_client:
            await client.aclose()


def parse_date(value: str) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        for form in (
            "%Y/%m/%d (%a) %H:%M",
            "%d %B %Y %I:%M %p",
            "%I:%M %p on %d %B, %Y",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                stamp = datetime.strptime(value, form)
                break
            except ValueError:
                continue
        else:
            raise BenchmarkError("unsupported benchmark timestamp") from None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def answers(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        if not value:
            raise BenchmarkError("empty ground truth")
        return (", ".join(str(part) for part in value),)
    if value is None:
        raise BenchmarkError("missing ground truth")
    return (str(value),)


def longmemeval(row: dict[str, Any]) -> Case:
    sessions: list[Session] = []
    evidence: list[str] = []
    for sid, date, turns in zip(
        row["haystack_session_ids"],
        row["haystack_dates"],
        row["haystack_sessions"],
        strict=True,
    ):
        converted: list[Turn] = []
        for index, turn in enumerate(turns):
            identifier = f"{sid}:{index}"
            converted.append(
                Turn(
                    id=identifier,
                    role=turn["role"],
                    text=turn["content"],
                    timestamp=parse_date(date),
                )
            )
            if turn.get("has_answer") is True:
                evidence.append(identifier)
        sessions.append(Session(id=sid, turns=tuple(converted)))
    sessions.sort(key=lambda session: (session.turns[0].timestamp, session.id))
    return Case(
        id=row["question_id"],
        category=row["question_type"],
        sessions=tuple(sessions),
        question=row["question"],
        answers=answers(row["answer"]),
        question_time=parse_date(row["question_date"]),
        abstention=row["question_id"].endswith("_abs"),
        evidence_turns=tuple(evidence),
        evidence_sessions=tuple(row.get("answer_session_ids", ())),
    )


def convomem(row: dict[str, Any], dataset: Dataset, origin: str) -> Iterator[Case]:
    # The original demo converter remains unchanged: it deliberately selects
    # ingestion-only sessions. Here QA records retain every supplied distractor.
    items = row.get("evidence_items", row.get("evidenceItems"))
    if items is None:
        raise BenchmarkError(
            "expected ConvoMem evidence_items; convert unsupported exports to normalized JSONL"
        )
    category = next(
        (part for part in PurePosixPath(origin).parts if part.endswith("_evidence")),
        dataset.split,
    )
    for position, item in enumerate(items):
        sessions: list[Session] = []
        evidence: list[str] = []
        gold = {
            (value["speaker"], value["text"])
            for value in item.get("message_evidences", ())
        }
        for ci, conversation in enumerate(
            row.get("conversations", item["conversations"])
        ):
            sid = str(conversation.get("id", f"conversation-{ci}"))
            turns: list[Turn] = []
            for ti, message in enumerate(conversation["messages"]):
                identifier = f"{sid}:{ti}"
                role = {"User": "user", "Assistant": "assistant", "Tool": "tool"}.get(
                    message["speaker"]
                )
                if role is None:
                    raise BenchmarkError("unsupported ConvoMem speaker")
                turns.append(
                    Turn.model_validate(
                        {
                            "id": identifier,
                            "role": role,
                            "text": message["text"],
                            "timestamp": dataset.missing_time_origin
                            + timedelta(seconds=ci, microseconds=ti),
                        }
                    )
                )
                if (message["speaker"], message["text"]) in gold:
                    evidence.append(identifier)
            sessions.append(Session(id=sid, turns=tuple(turns)))
        identifier = fingerprint(
            [origin, position, item.get("personId"), item["question"]]
        )[:24]
        yield Case(
            id=identifier,
            subject_id="subject-" + fingerprint(item["personId"])[:24]
            if item.get("personId")
            else None,
            category=category,
            sessions=tuple(sessions),
            question=item["question"],
            answers=answers(item["answer"]),
            abstention=category == "abstention_evidence",
            evidence_turns=tuple(evidence),
            evidence_sessions=tuple(
                s.id for s in sessions if any(t.id in evidence for t in s.turns)
            ),
            synthetic_timestamps=True,
            context_size=row.get("contextSize"),
        )


def locomo(row: dict[str, Any]) -> Iterator[Case]:
    conversation = row["conversation"]
    sessions: list[Session] = []
    for key in sorted(
        (
            key
            for key in conversation
            if key.startswith("session_") and key.removeprefix("session_").isdigit()
        ),
        key=lambda key: int(key.removeprefix("session_")),
    ):
        turns: list[Turn] = []
        for index, turn in enumerate(conversation[key]):
            # Both speakers are people whose memories are evaluated; never
            # silently relabel the second person's utterances as model output.
            turns.append(
                Turn(
                    id=turn["dia_id"],
                    role="user",
                    text=f"{turn['speaker']}: {turn['text']}"
                    + (
                        f"\nImage caption: {turn['blip_caption']}"
                        if turn.get("blip_caption")
                        else ""
                    ),
                    timestamp=parse_date(conversation[f"{key}_date_time"]),
                )
            )
        sessions.append(Session(id=key, turns=tuple(turns)))
    for index, qa in enumerate(row["qa"]):
        category = str(qa["category"])
        abstention = category == "5"
        yield Case(
            id=f"{row['sample_id']}:{index}",
            subject_id="locomo:" + str(row["sample_id"]),
            category=category,
            sessions=tuple(sessions),
            question=qa["question"],
            answers=answers(qa.get("answer", "unanswerable" if abstention else None)),
            abstention=abstention,
            evidence_turns=tuple(qa.get("evidence", ())),
        )


def adapt(row: Any, dataset: Dataset, origin: str) -> Iterator[Case]:
    if not isinstance(row, dict):
        raise BenchmarkError("dataset records must be objects")
    if dataset.format == "longmemeval":
        yield longmemeval(row)
    elif dataset.format == "convomem":
        yield from convomem(row, dataset, origin)
    elif dataset.format == "locomo":
        yield from locomo(row)
    else:
        yield Case.model_validate(row)


def prepare(dataset: Dataset, config: Experiment, root: Path) -> Path:
    directory = root / "raw" / dataset.id
    lock = json.loads((directory / "sources.lock.json").read_text())
    if lock["dataset_sha256"] != acquisition_fingerprint(dataset):
        raise BenchmarkError("source lock belongs to another dataset configuration")
    sources = tuple(Source.model_validate(row) for row in lock["sources"])
    target = root / "prepared" / dataset.id / "cases.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=target.parent)
    selected: list[tuple[int, str, Case]] = []
    seen: set[str] = set()
    count = 0
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            for source in sources:
                path = safe_path(directory, source.path)
                if digest(path) != source.sha256:
                    raise BenchmarkError("raw dataset changed since acquisition")
                for index, row in enumerate(records(path, config.max_record_bytes)):
                    if (
                        dataset.context_sizes
                        and isinstance(row, dict)
                        and row.get("contextSize") not in dataset.context_sizes
                    ):
                        continue
                    for case in adapt(row, dataset, source.path + f"#record-{index}"):
                        if case.id in seen:
                            raise BenchmarkError("duplicate case ID in dataset")
                        seen.add(case.id)
                        if (
                            dataset.categories
                            and case.category not in dataset.categories
                        ):
                            continue
                        if dataset.limit is None:
                            output.write(case.model_dump_json() + "\n")
                            count += 1
                        else:
                            rank = int(fingerprint([config.seed, case.id]), 16)
                            heapq.heappush(selected, (-rank, case.id, case))
                            if len(selected) > dataset.limit:
                                heapq.heappop(selected)
            for _, _, case in sorted(selected, key=lambda entry: (-entry[0], entry[1])):
                output.write(case.model_dump_json() + "\n")
                count += 1
        if count == 0:
            raise BenchmarkError("no benchmark cases selected")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    manifest = PreparedManifest(
        dataset=dataset, cases=count, cases_sha256=digest(target), sources=sources
    )
    atomic_write(
        target.with_name("manifest.json"), manifest.model_dump_json(indent=2) + "\n"
    )
    return target
