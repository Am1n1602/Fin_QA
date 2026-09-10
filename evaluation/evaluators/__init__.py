"""
Scoring functions for Fin_QA evaluation.

Phase 0: signatures + contracts only. No scoring logic yet — reference answers and
gold retrieval sets arrive in Phase 20, scoring implementation in Phase 18.

Planned evaluator families (roadmap Sec 39):

  numerical/   exact match, tolerance-based accuracy         (answer_type == "numeric")
  retrieval/   Recall@{1,3,5,10}, MRR, nDCG                   (needs gold sources)
  answer/      correctness, groundedness,
               citation precision / citation recall          (LLM-assisted + rule checks)
  safety/      unsupported-claim rate, abstention accuracy    (uses should_abstain)
  operations/  P50 / P95 latency, LLM cost per query          (from run reports)

Each evaluator takes (record: dict, result: dict) and returns a dict of metric_name -> value
plus a per-record verdict. A runner aggregates those across a dataset.
"""
from __future__ import annotations

from typing import Any, Protocol


class Evaluator(Protocol):
    name: str

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        """Return {"metrics": {...}, "verdict": "pass|fail|skip|na", "detail": "..."}."""
        ...


def abstention_verdict(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Phase 0 helper that already works: did the system abstain when it should have?

    Heuristic (v1 has no explicit abstain flag): treat an answer as an abstention when
    the answer text signals "no data / not available / could not classify" or no sources
    were produced for a should-abstain item.
    """
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
    return {
        "metrics": {"abstained": abstained},
        "verdict": "pass" if abstained else "fail",
        "detail": "expected an abstention / no-data response",
    }


def intent_match_verdict(record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Did the v1 classifier assign the intent this record expects? (skips when unpinned)"""
    expected = record.get("expected_intent_v1")
    got = result.get("intent")
    if not expected:
        return {"metrics": {"intent": got}, "verdict": "skip",
                "detail": "expected_intent_v1 not pinned"}
    return {
        "metrics": {"intent": got, "expected": expected},
        "verdict": "pass" if got == expected else "fail",
        "detail": f"expected {expected!r}, got {got!r}",
    }
