"""Acquisition, native formats, ground-truth separation and bounded preparation."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import httpx
import pytest

from agent_context.benchmarks.cli import load, plan
from agent_context.benchmarks.datasets import (
    acquire,
    adapt,
    discover,
    prepare,
    safe_path,
)
from agent_context.benchmarks.models import Case, Dataset, Experiment, HubSource, Source
from agent_context.benchmarks.runner import history
from agent_context.benchmarks.storage import records

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "benchmarks"
REVISION = "a" * 40


async def test_explicit_checksum_pins_a_versioned_non_git_source(tmp_path: Path) -> None:
    dataset = Dataset(id="checksum-source", format="normalized", revision="release-v1", split="test", license="synthetic", sources=(Source(path="data.json", url="https://datasets.example/releases/v1.json", sha256=sha256(b"[]").hexdigest()),))
    config = Experiment(name="test", datasets=(dataset,), artifacts=tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200,content=b"[]"))) as client:
        assert (await acquire(dataset, config, tmp_path, client=client)).exists()


def fixture_dataset(name: str, *, limit: int | None = None) -> Dataset:
    return Dataset.model_validate(
        {
            "id": name,
            "format": name,
            "revision": "fixture-v1",
            "split": "fixture",
            "license": "synthetic test input",
            "sources": [
                Source(
                    path=f"{name}.json", local=FIXTURES / f"{name}.json"
                ).model_dump()
            ],
            "limit": limit,
        }
    )


async def test_partial_multi_file_acquisition_resumes_without_redownloading(
    tmp_path: Path,
) -> None:
    dataset = fixture_dataset("longmemeval").model_copy(
        update={
            "revision": REVISION,
            "sources": tuple(
                Source(
                    path=f"{i}.json",
                    url=f"https://datasets.example/{REVISION}/{i}.json",
                )
                for i in (1, 2)
            ),
        }
    )
    config = Experiment(name="test", datasets=(dataset,), artifacts=tmp_path)
    counts: dict[str, int] = {}

    def response(request: httpx.Request) -> httpx.Response:
        counts[request.url.path] = counts.get(request.url.path, 0) + 1
        return httpx.Response(
            503
            if request.url.path.endswith("2.json") and counts[request.url.path] == 1
            else 200,
            content=b"[]",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await acquire(dataset, config, tmp_path, client=client)
        await acquire(dataset, config, tmp_path, client=client)
    assert counts[f"/{REVISION}/1.json"] == 1
    assert counts[f"/{REVISION}/2.json"] == 2


@pytest.mark.parametrize("name", ["longmemeval", "convomem", "locomo", "normalized"])
async def test_native_dataset_preparation_preserves_gold_and_is_reproducible(
    tmp_path: Path, name: str
) -> None:
    dataset = fixture_dataset(name)
    config = Experiment(name="test", datasets=(dataset,), artifacts=tmp_path)
    await acquire(dataset, config, tmp_path)
    path = prepare(dataset, config, tmp_path)
    original = path.read_bytes()
    cases = [Case.model_validate(row) for row in records(path, config.max_record_bytes)]
    assert cases and all(case.answers and case.question for case in cases)
    assert path.stat().st_mode & 0o777 == 0o600
    for case in cases:
        rendered = "\n".join(history(case))
        assert '"has_answer"' not in rendered and '"answers"' not in rendered
        assert (
            '"message_evidences"' not in rendered
            and '"containsEvidence"' not in rendered
        )
    assert prepare(dataset, config, tmp_path).read_bytes() == original
    if name == "longmemeval":
        assert [session.id for session in cases[0].sessions] == ["old", "new"]
        assert cases[0].evidence_turns == ("new:0",)
        assert cases[1].abstention
    if name == "locomo":
        assert all(
            turn.role == "user"
            for session in cases[0].sessions
            for turn in session.turns
        )
        assert cases[0].evidence_turns == ("D2:1",)


def test_premixed_convomem_keeps_outer_distractors_and_does_not_ingest_labels() -> None:
    dataset = fixture_dataset("convomem")
    item = json.loads((FIXTURES / "convomem.json").read_text())["evidence_items"][0]
    outer = {
        "evidenceItems": [item],
        "contextSize": 100,
        "conversations": [
            *item["conversations"],
            {
                "id": "filler",
                "messages": [
                    {"speaker": "User", "text": "My unrelated activity is climbing."}
                ],
            },
        ],
    }
    case = next(adapt(outer, dataset, "changing_evidence/file.json#record-0"))
    assert len(case.sessions) == 3 and case.sessions[-1].id == "filler"
    assert case.synthetic_timestamps and case.category == "changing_evidence"
    assert "containsEvidence" not in "\n".join(history(case))
    assert case.context_size == 100


async def test_changing_sample_limit_reuses_the_same_raw_data(tmp_path: Path) -> None:
    small = fixture_dataset("longmemeval", limit=1)
    config = Experiment(name="test", datasets=(small,), artifacts=tmp_path)
    await acquire(small, config, tmp_path)
    small_path = prepare(small, config, tmp_path)
    assert len(list(records(small_path, config.max_record_bytes))) == 1
    complete = small.model_copy(update={"limit": None})
    await acquire(complete, config, tmp_path)
    path = prepare(complete, config, tmp_path)
    assert len(list(records(path, config.max_record_bytes))) == 2


async def test_remote_acquisition_verifies_hash_reuses_cache_and_fails_on_tampering(
    tmp_path: Path,
) -> None:
    payload = (FIXTURES / "longmemeval.json").read_bytes()
    calls = 0

    async def response(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=payload)

    dataset = fixture_dataset("longmemeval").model_copy(
        update={
            "sources": (
                Source(
                    path="input.json",
                    url=f"https://datasets.example/{REVISION}/data.json",
                    sha256=sha256(payload).hexdigest(),
                ),
            ),
            "revision": REVISION,
        }
    )
    config = Experiment(name="test", datasets=(dataset,), artifacts=tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        await acquire(dataset, config, tmp_path, client=client)
        await acquire(dataset, config, tmp_path, client=client)
        assert calls == 1
        (tmp_path / "raw" / dataset.id / "input.json").write_text("corrupt")
        with pytest.raises(ValueError, match="checksum"):
            await acquire(dataset, config, tmp_path, client=client)


@pytest.mark.parametrize("failure", ["checksum", "size", "http"])
async def test_failed_download_never_publishes_a_cache_or_lock(
    tmp_path: Path, failure: str
) -> None:
    dataset = fixture_dataset("longmemeval").model_copy(
        update={
            "sources": (
                Source(
                    path="input.json",
                    url=f"https://datasets.example/{REVISION}/data.json",
                    sha256="0" * 64,
                ),
            ),
            "revision": REVISION,
        }
    )
    config = Experiment(
        name="test",
        datasets=(dataset,),
        artifacts=tmp_path,
        max_source_bytes=1 if failure == "size" else 100,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(403 if failure == "http" else 200, content=b"[]")
        )
    ) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            await acquire(dataset, config, tmp_path, client=client)
    assert not (tmp_path / "raw" / dataset.id / "input.json").exists()
    assert not (tmp_path / "raw" / dataset.id / "sources.lock.json").exists()


async def test_hub_pagination_matches_pinned_sources_and_lfs_checksums() -> None:
    dataset = fixture_dataset("convomem").model_copy(
        update={
            "sources": (),
            "revision": REVISION,
            "hub": HubSource(repository="owner/data", pattern="core/**/*.json"),
        }
    )

    def response(request: httpx.Request) -> httpx.Response:
        if "page=2" not in str(request.url):
            return httpx.Response(
                200,
                json=[{"type": "file", "path": "README.md"}],
                headers={
                    "Link": "<https://huggingface.co/api/datasets/owner/data/tree/"
                    + REVISION
                    + '?page=2>; rel="next"'
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "type": "file",
                    "path": "core/category/data.json",
                    "lfs": {"oid": "1" * 64},
                }
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        sources = await discover(dataset, client, 5)
    assert len(sources) == 1 and sources[0].sha256 == "1" * 64
    assert REVISION in str(sources[0].url)


def test_streaming_arrays_jsonl_unicode_and_malformed_data(tmp_path: Path) -> None:
    path = tmp_path / "input.json"
    values = [{"text": "é" * 70000}, {"text": "second"}]
    for text in (
        json.dumps(values, ensure_ascii=False),
        "\n".join(json.dumps(value) for value in values),
    ):
        path.write_text(text)
        assert list(records(path, 500000)) == values
    for text in ('[{"x":1},]', '[{"x":1} {"x":2}]', '[{"x":1}', "[]garbage", ""):
        path.write_text(text)
        with pytest.raises(ValueError):
            list(records(path, 500000))
    path.write_text(json.dumps(values))
    with pytest.raises(ValueError, match="byte limit"):
        list(records(path, 1024))


def test_path_escape_and_future_history_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        safe_path(tmp_path, "../outside.json")
    row = json.loads((FIXTURES / "longmemeval.json").read_text())[0]
    row["question_date"] = "2020-01-01"
    with pytest.raises(ValueError, match="after the question"):
        list(adapt(row, fixture_dataset("longmemeval"), "file"))


def test_catalog_config_selection_and_plan_make_no_provider_calls() -> None:
    path = FIXTURES.parents[2] / "benchmarks" / "configs" / "public.json"
    config = load(path, ["longmemeval-oracle"], 1)
    assert len(config.datasets) == 1 and config.datasets[0].limit == 1
    assert plan(config)["model_calls_made_by_plan"] == 0
    with pytest.raises(ValueError):
        load(path, ["missing"])
