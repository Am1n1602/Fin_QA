"""Confidence scoring for evidence and claims. Deliberately simple, documented
heuristics -- not a learned model. All outputs clamped to [0, 1].
"""
from __future__ import annotations

from finqa_v2.evidence.models import ClaimStatus, EvidenceType

# --- evidence ---
_EXACT_FACT = 0.98
_DERIVED_FACT = 0.90        # ebit / ebitda / total_debt / ...
_REVIEW_FLAGGED = 0.72      # source record failed an arithmetic identity check
_RATIO_CLEAN = 0.90
_RATIO_FLAGGED = 0.68
_DOC_FLOOR, _DOC_CEIL = 0.30, 0.85

_STATUS_FACTOR = {
    ClaimStatus.SUPPORTED: 1.00,
    ClaimStatus.PARTIALLY_SUPPORTED: 0.60,
    ClaimStatus.NOT_SUPPORTED: 0.20,
    ClaimStatus.INSUFFICIENT_EVIDENCE: 0.10,
}


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 6)


def fact_confidence(*, derived: bool = False, review_flagged: bool = False) -> float:
    if review_flagged:
        return _REVIEW_FLAGGED
    return _DERIVED_FACT if derived else _EXACT_FACT


def ratio_confidence(*, review_flagged: bool = False, missing_optional: bool = False) -> float:
    base = _RATIO_FLAGGED if review_flagged else _RATIO_CLEAN
    return _clamp(base - (0.1 if missing_optional else 0.0))


def document_confidence(*, rerank_score: float | None = None, rrf_score: float | None = None,
                        bm25_score: float | None = None, rank: int | None = None) -> float:
    """Map whatever retrieval signal we have into [_DOC_FLOOR, _DOC_CEIL]."""
    if rerank_score is not None:
        # cross-encoder logits roughly (-11, +11) -> squashed
        s = 1.0 / (1.0 + pow(2.718281828, -rerank_score / 3.0))
    elif rrf_score is not None:
        s = min(1.0, rrf_score / 0.05)                 # RRF with k=60, two lists -> ~0.033 max
    elif bm25_score is not None:
        s = min(1.0, bm25_score / 15.0)
    elif rank is not None:
        s = max(0.0, 1.0 - (rank - 1) / 10.0)
    else:
        s = 0.5
    return _clamp(_DOC_FLOOR + s * (_DOC_CEIL - _DOC_FLOOR))


def evidence_confidence_for_type(ev_type: EvidenceType, **kw) -> float:
    if ev_type in (EvidenceType.FINANCIAL_FACT, EvidenceType.CALCULATION):
        return fact_confidence(**{k: kw[k] for k in ("derived", "review_flagged") if k in kw})
    if ev_type in (EvidenceType.RATIO, EvidenceType.GROWTH):
        return ratio_confidence(**{k: kw[k] for k in ("review_flagged", "missing_optional") if k in kw})
    if ev_type in (EvidenceType.SEGMENT, EvidenceType.COMPARISON):
        return 0.9
    if ev_type is EvidenceType.DOCUMENT:
        return document_confidence(**{k: kw[k] for k in
                                      ("rerank_score", "rrf_score", "bm25_score", "rank") if k in kw})
    return 0.5


# --- claims ---
def claim_confidence(support_confidences, status: ClaimStatus) -> float:
    vals = [c for c in support_confidences if c is not None]
    base = (sum(vals) / len(vals)) if vals else 0.0
    return _clamp(base * _STATUS_FACTOR[ClaimStatus(status)])


def graph_confidence(claim_confidences, *, has_not_supported: bool = False) -> float:
    vals = [c for c in claim_confidences if c is not None]
    if not vals:
        return 0.0
    mean = sum(vals) / len(vals)
    return _clamp(min(mean, 0.4) if has_not_supported else mean)
