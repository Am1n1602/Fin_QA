"""Evidence Quality Gate: a safety check on DOCUMENT evidence before it is allowed to
support a causal/narrative claim, independent of retrieval ranking.

The retriever always returns its best-k candidates even when none of them are actually
relevant -- there is no floor on absolute relevance, only a relative ranking. This
catches that case (weak/thin/single-source evidence) and turns it into an honest,
specific limitation instead of letting a confidently-wrong answer stand. Operates only
on Evidence objects already in the workspace -- it makes no new retrieval call.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)


def check(docs, *, min_top_score: float = 0.50, min_count: int = 1,
          min_diversity: int = 1) -> GateResult:
    """`docs` is the DOCUMENT Evidence already gathered for this question
    (`Evidence.confidence` / `.document_id`)."""
    reasons: list[str] = []
    count = len(docs)
    top_score = max((e.confidence for e in docs), default=0.0)
    diversity = len({e.document_id for e in docs if e.document_id is not None})

    if count < min_count:
        reasons.append("no document evidence was retrieved")
    else:
        if top_score < min_top_score:
            reasons.append(
                f"the best-matching passage scored only {top_score:.2f} confidence "
                f"(below the {min_top_score:.2f} floor) -- likely not actually relevant"
            )
        if diversity < min_diversity:
            reasons.append("all retrieved passages come from a single document")

    return GateResult(passed=not reasons, reasons=reasons,
                      signals={"count": count, "top_score": top_score, "diversity": diversity})
