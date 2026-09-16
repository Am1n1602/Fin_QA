"""Evidence Quality Gate (§21): before generation, decide whether the DOCUMENT evidence
gathered so far is sufficient to support an answer, or whether the caller should flag a
controlled abstention instead of treating weak/scattered evidence as if it settles the
question.

Inputs (§21's own list): top score, number of relevant results, metadata match, section
match, evidence diversity -- all read directly off already-gathered `Evidence` objects
(or anything exposing the same `.confidence` / `.document_id` / `.section` /
`.company_id` shape); this never issues a new retrieval call.

Thresholds are calibrated against the retrieval_v21 benchmark (§21, full production
retrieval settings), not guessed: `document_confidence()`'s RRF-derived score is
rank-relative, not an absolute relevance signal, so a retriever ALWAYS returns something
even for a genuinely unanswerable question (Phase 1's own "spurious_hit_rate ~1.0"
finding). Sweeping `min_top_score` against ground truth ("was the gold chunk actually in
the top-5") on the full 380-case dataset: 0.30-0.45 catch 0/50 adversarial cases (the
floor in `document_confidence`'s [0.30, 0.85] clamp means every retrieved doc scores
>=0.30, so a low threshold is nearly a no-op); 0.50 catches 42/50 (84%) while only losing
12/165 genuine hits (recall 0.916); 0.65+ catches nearly all adversarial cases but loses
most genuine coverage too (recall <0.38). 0.50 is the chosen default -- the best
catch-rate-per-recall-lost point on that curve, not a threshold that eliminates every
false pass (it can't, given the signal).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.retrieval.section_weights import list_weighted_sections

PASS = "PASS"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

DEFAULT_MIN_TOP_SCORE = 0.50
DEFAULT_MIN_COUNT = 1
DEFAULT_MIN_DIVERSITY = 1


@dataclass(frozen=True, slots=True)
class GateResult:
    status: str
    reasons: tuple[str, ...] = ()
    signals: dict = field(default_factory=dict)

    @property
    def sufficient(self) -> bool:
        return self.status == PASS


def check(docs, *, intent: str | None = None, expected_company_id: int | None = None,
         min_top_score: float = DEFAULT_MIN_TOP_SCORE, min_count: int = DEFAULT_MIN_COUNT,
         min_diversity: int = DEFAULT_MIN_DIVERSITY) -> GateResult:
    docs = list(docs)
    scores = [d.confidence for d in docs if d.confidence is not None]
    top_score = max(scores) if scores else 0.0
    count = len(docs)
    doc_ids = {d.document_id for d in docs if d.document_id is not None}
    diversity = len(doc_ids)
    metadata_match = (expected_company_id is None
                      or any(d.company_id == expected_company_id for d in docs))
    hinted_sections = set(list_weighted_sections(intent)) if intent else set()
    section_match = (not hinted_sections) or any(d.section in hinted_sections for d in docs if d.section)

    reasons = []
    if count < min_count:
        reasons.append(f"only {count} document(s) retrieved (need >= {min_count})")
    if top_score < min_top_score:
        reasons.append(f"top evidence confidence {top_score:.2f} below threshold {min_top_score}")
    if diversity < min_diversity:
        reasons.append(f"evidence drawn from only {diversity} distinct document(s)")
    if expected_company_id is not None and not metadata_match:
        reasons.append("no retrieved evidence matches the expected company")
    if hinted_sections and not section_match:
        reasons.append("retrieved evidence falls outside the sections expected for this intent")

    status = INSUFFICIENT_EVIDENCE if reasons else PASS
    return GateResult(status=status, reasons=tuple(reasons),
                      signals={"top_score": top_score, "count": count, "diversity": diversity,
                              "metadata_match": metadata_match, "section_match": section_match})
