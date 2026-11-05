"""One staged command for acquisition, preparation, experiments and reports."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4

from agent_context.benchmarks.backend import ACEBackend, ScratchWorkspace
from agent_context.benchmarks.datasets import acquire, prepare
from agent_context.benchmarks.models import BenchmarkError, Experiment
from agent_context.benchmarks.providers import Providers
from agent_context.benchmarks.reports import summarize
from agent_context.benchmarks.runner import run
from context_graph.config import Settings


def load(
    path: Path,
    selected: list[str],
    limit: int | None = None,
    *,
    all_cases: bool = False,
) -> Experiment:
    config = Experiment.model_validate_json(path.read_text())
    datasets = []
    for dataset in config.datasets:
        if selected and dataset.id not in selected:
            continue
        sources = tuple(
            source.model_copy(update={"local": (path.parent / source.local).resolve()})
            if source.local and not source.local.is_absolute()
            else source
            for source in dataset.sources
        )
        local = dataset.local
        if local and not local.directory.is_absolute():
            local = local.model_copy(
                update={"directory": (path.parent / local.directory).resolve()}
            )
        changes: dict[str, object] = {"sources": sources, "local": local}
        if all_cases or limit is not None:
            changes["limit"] = None if all_cases else limit
        datasets.append(dataset.model_copy(update=changes))
    if not datasets or set(selected) - {d.id for d in datasets}:
        raise BenchmarkError("unknown or empty dataset selection")
    return config.model_copy(
        update={
            "datasets": tuple(datasets),
            "artifacts": (path.parent / config.artifacts).resolve(),
        }
    )


def plan(config: Experiment) -> dict[str, object]:
    prepared: dict[str, object] = {}
    for dataset in config.datasets:
        manifest = config.artifacts / "prepared" / dataset.id / "manifest.json"
        existing = json.loads(manifest.read_text()) if manifest.exists() else None
        matches = existing is not None and existing["dataset"] == dataset.model_dump(
            mode="json"
        )
        prepared[dataset.id] = {
            "format": dataset.format,
            "revision": dataset.revision,
            "split": dataset.split,
            "license": dataset.license,
            "limit": dataset.limit,
            "prepared_cases": existing["cases"]
            if existing is not None and matches
            else None,
            "prepared_configuration_matches": matches,
        }
    return {
        "experiment": config.name,
        "datasets": prepared,
        "methods": config.methods,
        "trials": config.trials,
        "context_utf8_bytes": config.context_bytes,
        "scoring": config.scoring,
        "provider_request_hard_limit_per_invocation": config.max_provider_requests,
        "model_calls_made_by_plan": 0,
        "requires_exclusive_empty_stores": any(
            method in config.methods for method in ("ace", "existing_retriever")
        ),
        "estimated_dollar_cost": None,
    }


async def execute(args: argparse.Namespace) -> Path | dict[str, object]:
    if args.command == "schema":
        return Experiment.model_json_schema()
    if args.command in {"score", "report"}:
        return summarize(args.run)
    config = load(args.config, args.dataset, args.limit, all_cases=args.all_cases)
    if args.max_requests is not None:
        config = Experiment.model_validate(
            {**config.model_dump(), "max_provider_requests": args.max_requests}
        )
    if args.command == "plan":
        return plan(config)
    if args.command == "clean":
        if not args.execute or not config.exclusive_scratch_stores:
            raise BenchmarkError(
                "cleanup requires explicit scratch-store configuration and --execute"
            )
        workspace = ScratchWorkspace(Settings(), args.run_id)
        try:
            await workspace.require_owner()
            await workspace.release()
        finally:
            await workspace.close()
        return {"cleaned_workspace_run_id": args.run_id}
    if args.command == "run" and not args.execute:
        return {
            **plan(config),
            "execution": "not started; add --execute for paid provider operations",
        }
    for dataset in config.datasets:
        await acquire(dataset, config, config.artifacts)
        if args.command != "acquire":
            prepare(dataset, config, config.artifacts)
    if args.command in {"acquire", "prepare"}:
        return config.artifacts
    graph = any(method in config.methods for method in ("ace", "existing_retriever"))
    if graph and not config.exclusive_scratch_stores:
        raise BenchmarkError(
            "ACE/legacy evaluation requires exclusive_scratch_stores=true and dedicated empty stores"
        )
    directory = (
        args.resume or config.artifacts / "runs" / f"{config.name}-{uuid4().hex[:12]}"
    )
    settings = Settings()
    providers = Providers(settings, config)
    workspace = ScratchWorkspace(settings, directory.name) if graph else None
    backend: ACEBackend | None = None
    try:
        if workspace:
            await workspace.claim()
            backend = ACEBackend(workspace, providers, config)
        try:
            result = await run(
                config, config.artifacts, providers, backend, resume=directory
            )
        finally:
            if (directory / "run.json").exists():
                summarize(directory)
        return result
    finally:
        if backend:
            await backend.close_case()
        if workspace:
            try:
                if workspace.claimed:
                    await workspace.release()
            finally:
                await workspace.close()
        await providers.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    for name in ("plan", "acquire", "prepare", "run", "clean"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, required=True)
        command.add_argument("--dataset", action="append", default=[])
        selection = command.add_mutually_exclusive_group()
        selection.add_argument("--limit", type=int)
        selection.add_argument("--all-cases", action="store_true")
        command.add_argument("--max-requests", type=int)
        command.add_argument("--execute", action="store_true")
        command.add_argument("--resume", type=Path)
        command.add_argument("--run-id")
    for name in ("score", "report"):
        command = commands.add_parser(name)
        command.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.command == "clean" and not args.run_id:
        parser.error(
            "clean requires the exact --run-id whose two store claims must match"
        )
    if getattr(args, "limit", None) is not None and args.limit < 1:
        parser.error("--limit must be positive")
    try:
        result = asyncio.run(execute(args))
    except Exception as error:
        # Provider/validation exceptions may contain credentials or raw turns.
        raise SystemExit(
            f"Benchmark {args.command} failed ({type(error).__name__})"
            + (f": {error}" if isinstance(error, BenchmarkError) else "")
            + ". Inspect the retained run artifacts and configuration; provider error bodies are not printed."
        ) from None
    print(
        result
        if isinstance(result, Path)
        else json.dumps(result, indent=2, default=str)
    )


if __name__ == "__main__":
    main()
