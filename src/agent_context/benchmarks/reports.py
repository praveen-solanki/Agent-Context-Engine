"""Re-score immutable answers and emit reproducible JSON/Markdown/QA exports."""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

from agent_context.benchmarks.models import Answer, Case, Experiment, JudgeDecision
from agent_context.benchmarks.scoring import JUDGE_VERSION, judge_payload, lexical
from agent_context.benchmarks.storage import atomic_write, fingerprint


def percentile(values: list[float], fraction: float) -> float | None:
    return (
        sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]
        if values
        else None
    )


def bootstrap(values: list[float], seed: int) -> list[float] | None:
    # Cluster at case level; repeated generations are not independent tasks.
    if len(values) < 10:
        return None
    rng = random.Random(seed)
    samples = sorted(mean(rng.choices(values, k=len(values))) for _ in range(1000))
    return [samples[24], samples[974]]


def measured_stages(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    values: list[tuple[str, dict[str, Any]]] = []
    if result["ingestion"]:
        values.append(("ingestion_shared_graph_setup", result["ingestion"]))
    values.extend(
        ("preparation/" + method, value)
        for method, value in result["preparation"].items()
    )
    values.extend(
        ("answer_and_judge/" + row["method"], row["total_measurement"])
        for row in result["trials"]
    )
    return values


def accumulate(
    totals: dict[str, dict[str, Any]], stage: str, measurement: dict[str, Any]
) -> None:
    aggregate = totals.setdefault(
        stage, {"seconds": 0.0, "known_cost_usd": 0.0, "usage": {}}
    )
    aggregate["seconds"] += measurement["seconds"]
    if measurement["known_cost_usd"] is None:
        aggregate["known_cost_usd"] = None
    elif aggregate["known_cost_usd"] is not None:
        aggregate["known_cost_usd"] += measurement["known_cost_usd"]
    for role, usage in measurement["usage"].items():
        total = aggregate["usage"].setdefault(
            role,
            {
                "model": usage["model"],
                **{field: 0 for field in usage if field != "model"},
            },
        )
        for field, value in usage.items():
            if field != "model":
                total[field] += value


def summarize(directory: Path) -> Path:
    run = json.loads((directory / "run.json").read_text())
    config = Experiment.model_validate(run["provenance"]["config"])
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    exports: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    stage_totals: dict[str, dict[str, Any]] = {}
    all_attempt_totals: dict[str, dict[str, Any]] = {}
    method_accounts: dict[str, dict[str, Any]] = {}
    attempted_cases = 0
    archived_attempts: list[str] = []
    for name in run["case_files"]:
        result = json.loads((directory / name).read_text())
        case = Case.model_validate(result["case"])
        archived_attempts.extend(
            p.name for p in directory.glob(Path(name).stem + "-attempt-*.json")
        )
        attempted_cases += 1
        by_trial = {(row["method"], row["trial"]): row for row in result["trials"]}
        for method in config.methods:
            account = method_accounts.setdefault(
                f"{result['dataset']}/{method}",
                {
                    "setup_seconds": 0.0,
                    "setup_known_cost_usd": 0.0,
                    "answer_and_judge_seconds": 0.0,
                    "answer_and_judge_known_cost_usd": 0.0,
                },
            )
            setup = (
                [result["preparation"][method]]
                if method in result["preparation"]
                else []
            )
            if method in ("ace", "existing_retriever") and result["ingestion"]:
                setup.append(result["ingestion"])
            for measurement in setup:
                account["setup_seconds"] += measurement["seconds"]
                if measurement["known_cost_usd"] is None:
                    account["setup_known_cost_usd"] = None
                elif account["setup_known_cost_usd"] is not None:
                    account["setup_known_cost_usd"] += measurement["known_cost_usd"]
            for trial in range(1, config.trials + 1):
                row = by_trial.get((method, trial))
                if row is None and not result["completed"]:
                    continue
                error = (
                    row.get("error_type")
                    if row
                    else result.get("case_error_type", "CaseFailed")
                )
                if row:
                    measurement = row["total_measurement"]
                    account["answer_and_judge_seconds"] += measurement["seconds"]
                    if measurement["known_cost_usd"] is None:
                        account["answer_and_judge_known_cost_usd"] = None
                    elif account["answer_and_judge_known_cost_usd"] is not None:
                        account["answer_and_judge_known_cost_usd"] += measurement[
                            "known_cost_usd"
                        ]
                answer = (
                    Answer.model_validate(row["answer"])
                    if row and row["answer"] is not None
                    else None
                )
                scores = (
                    lexical(case, answer)
                    if answer
                    else {
                        "exact_match": 0.0,
                        "token_f1": 0.0,
                        "lexical_correct": False,
                        "abstention_correct": False,
                    }
                )
                judged = row.get("judge") if row else None
                if judged and answer:
                    if (
                        row is None
                        or row.get("judge_version") != JUDGE_VERSION
                        or row.get("judge_input_sha256")
                        != fingerprint(judge_payload(case, answer))
                    ):
                        error, judged = "JudgeInputMismatch", None
                    else:
                        judged = JudgeDecision.model_validate(judged).model_dump()
                correct = bool(
                    not error
                    and answer
                    and (
                        judged and judged["correct"]
                        if config.scoring == "judge"
                        else scores["lexical_correct"]
                    )
                )
                scored = {
                    "case_id": case.id,
                    "cluster_id": case.subject_id or case.id,
                    "category": case.category,
                    "correct": correct,
                    "failed": bool(error or answer is None),
                    "lexical": scores,
                    "judge_available": judged is not None,
                    "answer_seconds": (row or {})
                    .get("answer_measurement", {})
                    .get("seconds"),
                    "total_seconds": (row or {})
                    .get("total_measurement", {})
                    .get("seconds"),
                    "retrieval": (row or {}).get("scores"),
                }
                groups[f"{result['dataset']}/{method}"].append(scored)
                if answer:
                    exports[(result["dataset"], method, trial)].append(
                        {"question_id": case.id, "hypothesis": answer.answer}
                    )
        for stage, measurement in measured_stages(result):
            accumulate(stage_totals, stage, measurement)
            accumulate(all_attempt_totals, stage, measurement)
        for archived in directory.glob(Path(name).stem + "-attempt-*.json"):
            for stage, measurement in measured_stages(json.loads(archived.read_text())):
                accumulate(all_attempt_totals, stage, measurement)
    summary: dict[str, Any] = {}
    for key, rows in sorted(groups.items()):
        case_scores: dict[str, list[float]] = defaultdict(list)
        cluster_scores: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            case_scores[row["case_id"]].append(float(row["correct"]))
            cluster_scores[row["cluster_id"]].append(float(row["correct"]))
        latencies = [
            row["answer_seconds"] for row in rows if row["answer_seconds"] is not None
        ]
        categories = {
            category: mean(
                float(row["correct"]) for row in rows if row["category"] == category
            )
            for category in sorted({row["category"] for row in rows})
        }
        account = method_accounts[key]
        summary[key] = {
            **account,
            "setup_inclusive_seconds_per_measured_trial": (
                account["setup_seconds"] + account["answer_and_judge_seconds"]
            )
            / len(rows),
            "attempted_trials": len(rows),
            "failed_trials": sum(row["failed"] for row in rows),
            "correct_trials": sum(row["correct"] for row in rows),
            "accuracy_on_attempted": mean(row["correct"] for row in rows),
            "case_macro_accuracy": mean(
                mean(values) for values in case_scores.values()
            ),
            "independent_clusters": len(cluster_scores),
            "cluster_macro_accuracy": mean(
                mean(values) for values in cluster_scores.values()
            ),
            "cluster_bootstrap_95_percent_interval": bootstrap(
                [mean(values) for values in cluster_scores.values()], config.seed
            ),
            "category_accuracy": categories,
            "mean_token_f1": mean(row["lexical"]["token_f1"] for row in rows),
            "answer_latency_samples": len(latencies),
            "answer_p50_seconds": median(latencies) if latencies else None,
            "answer_p95_seconds": percentile(latencies, 0.95)
            if len(latencies) >= 20
            else None,
            "answer_p99_seconds": percentile(latencies, 0.99)
            if len(latencies) >= 100
            else None,
        }
        for field in ("evidence_turn_recall", "evidence_session_recall"):
            values = [
                row["retrieval"][field]
                for row in rows
                if row["retrieval"] and row["retrieval"][field] is not None
            ]
            summary[key][field] = mean(values) if values else None
    planned_cases = sum(
        manifest["cases"] for manifest in run["provenance"]["datasets"].values()
    )
    report: dict[str, Any] = {
        "run_id": run["run_id"],
        "completed": run["completed"],
        "scoring": config.scoring,
        "planned_cases": planned_cases,
        "attempted_cases": attempted_cases,
        "planned_trials": planned_cases * config.trials * len(config.methods),
        "scored_trials": sum(len(rows) for rows in groups.values()),
        "summary": summary,
        "stage_totals_current_attempts": stage_totals,
        "stage_totals_including_archived_attempts": all_attempt_totals,
        "archived_incomplete_attempts": archived_attempts,
        "limitations": [
            "Lexical EM/F1 are deterministic diagnostics, not official semantic benchmark accuracy.",
            "Optional judge follows category-aware criteria but uses a disclosed configurable model/schema; it is not claimed to reproduce official leaderboard scores.",
            "Intervals resample subjects/conversations when identified, otherwise cases; fewer than ten clusters have no interval. Repeated generations are not independent tasks. Small samples have no tail-latency claim.",
            "Shared ingestion is charged once in actual stage totals; both ACE and legacy require it. Setup-inclusive per-trial figures amortize only these measured trials, not future production queries. Seeds are requested, not a guarantee of backend determinism.",
            "Missing provider usage/prices or failed requests make stage dollar cost unknown; reported tokens are not complete billing.",
            "Current-attempt and all-attempt stage totals are separate; the latter includes archived incomplete attempts. Method setup attribution includes shared ingestion for ACE and legacy separately; actual global charges count it once.",
            "Evidence recall is available only for methods with exact source mapping and nonempty labels; summary/legacy null is not zero recall.",
            "ACE evidence inspection is bounded by the existing endpoint. Source references establish provenance, not semantic support of every generated assertion.",
            "Normalized task datasets evaluate supplied offline QA/next-action references, not interactive environment/tool execution success.",
            "Dataset clocks are replay clocks; synthesized ConvoMem timestamps preserve source order, not real-world elapsed time.",
        ],
    }
    atomic_write(directory / "summary.json", json.dumps(report, indent=2) + "\n")
    lines = [
        f"# {run['run_id']}",
        "",
        f"Completed: {run['completed']}. Scoring: {config.scoring}. Cases: {attempted_cases}/{planned_cases}.",
        "",
        "| Dataset / method | Trials | Failures | Accuracy on attempted | Token F1 | Answer p50 seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {key} | {row['attempted_trials']} | {row['failed_trials']} | {row['accuracy_on_attempted']:.4f} | {row['mean_token_f1']:.4f} | {row['answer_p50_seconds']} |"
        for key, row in summary.items()
    )
    lines += [
        "",
        "This report describes only the recorded run. Fixture/mock runs do not establish dataset quality or production performance.",
        "",
        *["- " + note for note in report["limitations"]],
        "",
        "See run.json for exact configuration, source checksums, model IDs, prompt hashes and code provenance; case files retain original answers, contexts, scores and stage usage.",
    ]
    atomic_write(directory / "report.md", "\n".join(lines) + "\n")
    for (dataset, method, trial), values in exports.items():
        atomic_write(
            directory / "exports" / f"{dataset}-{method}-trial-{trial}.jsonl",
            "".join(json.dumps(value, ensure_ascii=False) + "\n" for value in values),
        )
    return directory / "summary.json"
