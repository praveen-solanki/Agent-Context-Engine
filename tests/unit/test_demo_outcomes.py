"""Task completion is distinct from language keywords or plausible citations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_context.demo_cli import DOCUMENT, DOCUMENT_ID
from agent_context.evaluation import RecommendationAssessment, recommendation_checks


ANSWER = "Recomiendo la Opción A: es la más barata y funciona sin conexión."
EVIDENCE = "Option A costs 10 units and supports offline operation."


def assessment(**changes: object) -> RecommendationAssessment:
    return RecommendationAssessment.model_validate({
        "status": "completed", "selected_option": "A", "report_language": "Spanish",
        "recommendation_quote": ANSWER, "evidence_quote": EVIDENCE, **changes,
    })


def checks(value: RecommendationAssessment, answer: str = ANSWER, *, citations: tuple[str, ...] = (DOCUMENT_ID,)) -> dict[str, bool]:
    return recommendation_checks(value, answer=answer, document=DOCUMENT,
                                 expected_option="A", expected_language="Spanish",
                                 citations=citations, document_id=DOCUMENT_ID,
                                 required_document_facts=(EVIDENCE.rstrip("."),))


def test_final_supported_recommendation_passes_each_independent_gate() -> None:
    assert all(checks(assessment()).values())


def test_saved_six_flag_false_positive_is_rejected_even_with_a_forged_completed_label() -> None:
    report = json.loads((Path(__file__).resolve().parents[2] / "docs/ace/results/live-demo.json").read_text())
    saved_answer: str = report["sessions"][-1]["answer"]
    assert all(report["checks"].values())
    assert any(word in saved_answer.lower() for word in ("opción", "recomiendo", "recomendación"))
    # A completed label alone cannot manufacture an actual choice in the quote.
    result = checks(assessment(recommendation_quote=saved_answer), saved_answer)
    assert not result["option_present_in_answer_quote"]
    assert not all(result.values())


@pytest.mark.parametrize("status", ["abstained", "ambiguous", "contradictory"])
def test_noncompleted_answer_is_rejected_despite_spanish_and_source_ids(status: str) -> None:
    assert not checks(assessment(status=status))["recommendation_delivered"]


@pytest.mark.parametrize("changes", [
    {"selected_option": "B"},
    {"report_language": "English"},
    {"recommendation_quote": "A recommendation that never appeared"},
    {"evidence_quote": "Option A costs 1 unit and is free"},
    {"evidence_quote": "Option A"},
])
def test_wrong_choice_stale_language_fabricated_or_incomplete_support_fails(changes: dict[str, object]) -> None:
    assert not all(checks(assessment(**changes)).values())


def test_memory_only_citation_does_not_prove_document_facts() -> None:
    assert not checks(assessment(), citations=("memory:language-preference",))["document_cited"]
