"""Credentialed three-session demonstration using separate user/host identities."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from dotenv import load_dotenv

from agent_context.client import AgentContextClient
from agent_context.demo import ResearchAssistant
from agent_context.handoff import HandoffInput
from context_graph.config import Settings
from context_graph.providers.chat_backend import ChatLLMProvider


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
    llm = ChatLLMProvider(backend=settings.chat, llm=settings.llm, retry=settings.retry)
    run_id = uuid4().hex[:12]
    assistant = ResearchAssistant(
        user_client=user,
        host_client=host,
        llm=llm,
        documents={
            "research-brief": "Option A costs 10 units and supports offline operation. Option B costs 20 units and requires a network."
        },
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
        report["sessions"] = [
            {
                "session": name,
                "answer": turn.answer,
                "context": [i.text for i in turn.bundle.items],
                "context_tokens_upper_bound": turn.bundle.token_count,
                "model_calls": turn.model_calls,
                "verified_reads": len(turn.completed),
            }
            for name, turn in (("A", a), ("B", b), ("C", c))
        ]
        report["replay_cached"] = replay.cached
        report["checks"] = {
            "read_each_session": all(turn.completed for turn in (a, b, c)),
            "citations_each_session": all(
                "research-brief" in turn.answer for turn in (a, b, c)
            ),
            "current_language_in_C": any(
                "spanish" in i.text.lower() for i in c.bundle.items
            ),
            "no_superseded_english_in_C": all(
                "english" not in i.text.lower() for i in c.bundle.items
            ),
            "spanish_answer_in_C": any(
                word in c.answer.lower()
                for word in ("opción", "recomiendo", "recomendación")
            ),
            "replay_cached": replay.cached and replay.model_calls == 0,
        }
        report["elapsed_seconds"] = round(perf_counter() - start, 3)
        report["limitations"] = [
            "Synthetic bounded document scenario",
            "No cross-provider switch in this run",
            "End-to-end timing includes live ingestion and provider calls; no per-token price estimate",
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
