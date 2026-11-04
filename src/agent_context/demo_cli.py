"""Credentialed three-session demonstration using separate user/host identities."""

from __future__ import annotations

import asyncio
import json
import os
import hashlib
import subprocess
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv

from agent_context.client import AgentContextClient
from agent_context.demo import ResearchAssistant, DemoSettings, SYSTEM
from agent_context.evaluation import (
    COMPLETION_VERIFIER_VERSION,
    MeteredTransport,
    assess_recommendation,
    recommendation_checks,
)
from agent_context.handoff import HandoffInput
from agent_context.contracts import utcnow
from context_graph.config import Settings
from context_graph.prompts import PROMPT_VERSION
from context_graph.providers.chat_backend import ChatLLMProvider

DOCUMENT_ID = "research-brief"
DOCUMENT = "Option A costs 10 units and supports offline operation. Option B costs 20 units and requires a network."
TASK = "Recommend the cheapest option that works offline, supported by the supplied brief."


async def run_demo() -> None:
    load_dotenv(override=False)
    settings = Settings()
    user = AgentContextClient(
        base_url=os.environ.get("ACE_API_URL", "http://127.0.0.1:8000"),
        bearer_token=os.environ["ACE_DEMO_USER_TOKEN"],
    )
    host = AgentContextClient(
        base_url=os.environ.get("ACE_API_URL", "http://127.0.0.1:8000"),
        bearer_token=os.environ["ACE_DEMO_AGENT_TOKEN"],
    )
    meter = MeteredTransport(settings)
    llm = ChatLLMProvider(backend=settings.chat, llm=settings.llm, transport=meter)
    run_id = uuid4().hex[:12]
    assistant = ResearchAssistant(
        user_client=user,
        host_client=host,
        llm=llm,
        documents={DOCUMENT_ID: DOCUMENT},
        settings=DemoSettings(require_sources=True),
    )
    report: dict[str, object] = {"run_id": run_id, "model": llm.model, "sessions": []}
    start = perf_counter()
    try:
        a = await assistant.turn(
            session_id=f"{run_id}-A",
            turn_id="request",
            message="My report language preference is English. Always write my research reports in English. Read research-brief and recommend the cheapest option that works offline, citing the document.",
        )
        handoff_id = f"research-{run_id}"
        await user.prepare_handoff(
            HandoffInput(
                handoff_id=handoff_id,
                idempotency_key=f"{run_id}-A-close",
                expected_version=0,
                project_id="research-project",
                task_id="compare-options",
                source_session_id=f"{run_id}-A",
                goal="Compare the supplied research options",
                requirements=("Use concise English summaries",),
                completed=a.completed,
                pending=("Confirm the final recommendation",),
            )
        )
        b = await assistant.turn(
            session_id=f"{run_id}-B",
            turn_id="correction",
            correction=True,
            message="Correction: my report language preference is Spanish instead of English. From now on always write my research reports in Spanish. Read research-brief and recommend the cheapest option that works offline with a citation.",
            handoff_id=handoff_id,
            handoff_version=1,
        )
        await user.prepare_handoff(
            HandoffInput(
                handoff_id=handoff_id,
                idempotency_key=f"{run_id}-B-close",
                expected_version=1,
                project_id="research-project",
                task_id="compare-options",
                source_session_id=f"{run_id}-B",
                goal="Compare the supplied research options",
                requirements=("Use concise Spanish summaries",),
                completed=b.completed,
                pending=("Deliver the final recommendation",),
            )
        )
        c = await assistant.turn(
            session_id=f"{run_id}-C",
            turn_id="continue",
            message="Continue the research using my current summary language requirement. Read research-brief and deliver the final cited recommendation.",
            handoff_id=handoff_id,
            handoff_version=2,
        )
        replay = await assistant.turn(
            session_id=f"{run_id}-C",
            turn_id="continue",
            message="Continue the research using my current summary language requirement. Read research-brief and deliver the final cited recommendation.",
            handoff_id=handoff_id,
            handoff_version=2,
        )
        host_usage = (meter.calls, meter.prompt_tokens, meter.completion_tokens)
        assessments = [
            await assess_recommendation(llm, answer=turn.answer, document=DOCUMENT, task=TASK)
            for turn in (a, b, c)
        ]
        outcomes = [
            recommendation_checks(
                assessment, answer=turn.answer, document=DOCUMENT,
                expected_option="A", expected_language=language,
                citations=turn.citations, document_id=DOCUMENT_ID,
                required_document_facts=(DOCUMENT.split(". ", 1)[0],),
            )
            for turn, assessment, language in zip(
                (a, b, c), assessments, ("English", "Spanish", "Spanish"), strict=True
            )
        ]
        report["sessions"] = [
            {
                "session": name,
                "answer": turn.answer,
                "context": [i.text for i in turn.bundle.items],
                "context_tokens_upper_bound": turn.bundle.token_count,
                "model_calls": turn.model_calls,
                "verified_reads": len(turn.completed),
                "citations": turn.citations,
                "assessment": assessment.model_dump(mode="json"),
                "outcome_checks": outcome,
            }
            for name, turn, assessment, outcome in zip(
                ("A", "B", "C"), (a, b, c), assessments, outcomes, strict=True
            )
        ]
        report["replay_cached"] = replay.cached
        report["checks"] = {
            "read_each_session": all(turn.completed for turn in (a, b, c)),
            "citations_each_session": all(
                DOCUMENT_ID in turn.citations for turn in (a, b, c)
            ),
            "current_language_in_C": any(
                "spanish" in i.text.lower() for i in c.bundle.items
            ),
            "no_superseded_english_in_C": all(
                "english" not in i.text.lower() for i in c.bundle.items
            ),
            "spanish_answer_in_C": assessments[2].report_language == "Spanish",
            "recommendations_each_session": all(all(outcome.values()) for outcome in outcomes),
            "replay_cached": replay.cached and replay.model_calls == 0,
        }
        report["elapsed_seconds"] = round(perf_counter() - start, 3)
        try:
            revision = subprocess.run(
                ["git", "-C", str(Path(__file__).resolve().parents[2]), "rev-parse", "HEAD"],
                capture_output=True, text=True, check=False,
            )
            source_revision = revision.stdout.strip() if revision.returncode == 0 else None
        except OSError:
            source_revision = None  # Packaged installs need not contain Git.
        report["verification"] = {
            "version": COMPLETION_VERIFIER_VERSION,
            "judge_model": llm.model,
            "timestamp": utcnow().isoformat(),
            "source_revision": source_revision,
            "demo_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "host_prompt_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
            "verifier_source_sha256": hashlib.sha256(Path(__file__).with_name("evaluation.py").read_bytes()).hexdigest(),
            "extraction_prompt_version": PROMPT_VERSION,
            "document_sha256": hashlib.sha256(DOCUMENT.encode()).hexdigest(),
        }
        report["provider_usage"] = {
            "host_chat": dict(zip(("calls", "prompt_tokens", "completion_tokens"), host_usage, strict=True)),
            "verification_chat": {
                "calls": meter.calls - host_usage[0],
                "prompt_tokens": meter.prompt_tokens - host_usage[1],
                "completion_tokens": meter.completion_tokens - host_usage[2],
            },
            "worker_ingestion_usage": None,
        }
        report["limitations"] = [
            "Synthetic bounded document scenario",
            "No cross-provider switch in this run",
            "End-to-end timing includes live ingestion and provider calls; no per-token price estimate",
            "Completion classification uses the same model as generation; exact quotes, choice, language and cited document are independently checked, but this is not universal semantic proof",
            "Host and verifier provider usage are separate; worker ingestion usage is not included, so total billed cost is unknown",
        ]
        output = Path("data/ace_demo")
        output.mkdir(parents=True, exist_ok=True)
        path = output / f"{run_id}.json"
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(
            json.dumps(
                {
                    "report": str(path),
                    "checks": report["checks"],
                    "elapsed_seconds": report["elapsed_seconds"],
                }
            )
        )
        if not all(report["checks"].values()):
            raise RuntimeError(
                "research demo outcome checks failed; inspect the report"
            )
    finally:
        await llm.aclose()
        await user.aclose()
        await host.aclose()


def main() -> None:
    asyncio.run(run_demo())
