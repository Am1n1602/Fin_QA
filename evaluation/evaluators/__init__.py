"""Scoring functions for Fin_QA evaluation (roadmap §39). See docs/file-guide.md.

Per-record evaluators implement `Evaluator`: `.score(record, result) -> {metrics, verdict, detail}`
where `verdict` is one of pass | fail | warn | na | skip. `result` is a ReasoningResult.to_dict()
(has `response`, `verification`, `trace`, `latency_ms`, ...). Aggregate-only evaluators
(retrieval, operations) expose `.run(...)` instead and are driven directly by the runner.
"""
from __future__ import annotations

from typing import Any, Protocol

from evaluation.evaluators.answer import (
    CitationEvaluator,
    CorrectnessEvaluator,
    GroundednessEvaluator,
)
from evaluation.evaluators.numerical import NumericalEvaluator
from evaluation.evaluators.operations import OperationsEvaluator
from evaluation.evaluators.retrieval import RetrievalEvaluator, score_retrieval
from evaluation.evaluators.safety import (
    AbstentionEvaluator,
    UnsupportedClaimEvaluator,
    did_abstain,
)

__all__ = [
    "Evaluator", "DEFAULT_EVALUATORS", "score_record",
    "NumericalEvaluator", "CorrectnessEvaluator", "GroundednessEvaluator",
    "CitationEvaluator", "AbstentionEvaluator", "UnsupportedClaimEvaluator",
    "RetrievalEvaluator", "OperationsEvaluator", "score_retrieval", "did_abstain",
    "abstention_verdict", "intent_match_verdict",
]


class Evaluator(Protocol):
    name: str

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Return {"metrics": {...}, "verdict": "pass|fail|warn|skip|na", "detail": "..."}."""
        ...


DEFAULT_EVALUATORS: list[Evaluator] = [
    NumericalEvaluator(),
    CorrectnessEvaluator(),
    GroundednessEvaluator(),
    CitationEvaluator(),
    AbstentionEvaluator(),
    UnsupportedClaimEvaluator(),
]


def score_record(record: dict[str, Any], result: dict[str, Any],
                 evaluators: list[Evaluator] | None = None) -> dict[str, Any]:
    """Run every per-record evaluator, keyed by name."""
    return {e.name: e.score(record, result) for e in (evaluators or DEFAULT_EVALUATORS)}


# ---------------------------------------------------------------------------
# Phase 0 verdict helpers — still used by the v1 baseline_runner.
# ---------------------------------------------------------------------------
def abstention_verdict(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Did the system abstain when it should have? (v1-shaped result dict)."""
    should = bool(record.get("should_abstain"))
    answer = (result.get("answer") or "").lower()
    signals = (
        "not available in the database",
        "no relevant passages were found",
        "could not confidently classify",
        "no llm synthesis is available",
        "needs a specific",
    )
    abstained = any(s in answer for s in signals) or (
        not result.get("sources") and record.get("answer_type") == "abstain"
    )
    if not should:
        return {"metrics": {"abstained": abstained}, "verdict": "na",
                "detail": "record does not require abstention"}
    return {"metrics": {"abstained": abstained},
            "verdict": "pass" if abstained else "fail",
            "detail": "expected an abstention / no-data response"}


def intent_match_verdict(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Did the classifier assign the expected intent? (skips when unpinned)."""
    expected = record.get("expected_intent_v1")
    got = result.get("intent")
    if not expected:
        return {"metrics": {"intent": got}, "verdict": "skip",
                "detail": "expected_intent_v1 not pinned"}
    return {"metrics": {"intent": got, "expected": expected},
            "verdict": "pass" if got == expected else "fail",
            "detail": f"expected {expected!r}, got {got!r}"}
