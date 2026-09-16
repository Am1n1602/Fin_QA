"""Citation Evaluation (§22): claim -> evidence_id -> document -> page -> source text,
scored against verified gold citations for a question.

Complements `evaluation/evaluators/answer.py`'s existing `CitationEvaluator` (whole-answer,
fuzzy title/section matching against a record's loosely-specified `reference_sources`)
with an exact, document_id-level, PER-CLAIM view -- the roadmap's own full metric list:
citation precision, citation recall, citation F1, document accuracy, page accuracy,
claim-to-evidence accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldCitation:
    """A verified real citation for a question. `document_id` must come from a real DB
    probe (e.g. `evaluation/datasets/retrieval_v21/probe.py`), never fabricated -- the
    same discipline Phase 1's retrieval benchmark dataset was built under. `page` is
    optional; page-level gold is stricter than most datasets can honestly provide."""
    document_id: int
    page: int | None = None


def evaluate(claims: list[dict], evidence_by_id: dict[str, dict], gold: list[GoldCitation]) -> dict:
    """`claims`: a response's own `claims` list (`{"evidence_ids": [...], ...}`, as produced
    by `finqa_v2.evidence.ClaimGraph`/`reasoning.synthesize`). `evidence_by_id`: the
    response's `evidence` list keyed by `evidence_id` (`{"type": "document",
    "document_id": ..., "page": ..., ...}`, as produced by `Evidence.to_dict()`). `gold`:
    verified citations for the question -- `[]` means "no gold available", in which case
    every gold-dependent metric is `None` rather than a misleading `0.0` (matching this
    project's existing "na means na" convention, see `evaluators/answer.py`)."""
    gold_by_doc = {g.document_id: g for g in gold}

    n_traceable = 0
    cited_docs: list[dict] = []
    for c in claims:
        ids = c.get("evidence_ids") or []
        resolved = [evidence_by_id[i] for i in ids if i in evidence_by_id]
        if ids and len(resolved) == len(ids):
            n_traceable += 1
        cited_docs.extend(e for e in resolved if e.get("type") == "document")
    claim_to_evidence_accuracy = (n_traceable / len(claims)) if claims else None

    got_doc_ids = {d["document_id"] for d in cited_docs if d.get("document_id") is not None}

    if not gold:
        precision = recall = f1 = document_accuracy = page_accuracy = None
    else:
        matched = got_doc_ids & set(gold_by_doc)
        precision = (len(matched) / len(got_doc_ids)) if got_doc_ids else 0.0
        recall = len(matched) / len(gold_by_doc)
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

        doc_checked = [d for d in cited_docs if d.get("document_id") is not None]
        doc_hits = sum(1 for d in doc_checked if d["document_id"] in gold_by_doc)
        document_accuracy = (doc_hits / len(doc_checked)) if doc_checked else None

        page_checked = [d for d in doc_checked
                        if d["document_id"] in gold_by_doc
                        and gold_by_doc[d["document_id"]].page is not None
                        and d.get("page") is not None]
        page_hits = sum(1 for d in page_checked if d["page"] == gold_by_doc[d["document_id"]].page)
        page_accuracy = (page_hits / len(page_checked)) if page_checked else None

    return {
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1": round(f1, 4) if f1 is not None else None,
        "document_accuracy": round(document_accuracy, 4) if document_accuracy is not None else None,
        "page_accuracy": round(page_accuracy, 4) if page_accuracy is not None else None,
        "claim_to_evidence_accuracy": (round(claim_to_evidence_accuracy, 4)
                                       if claim_to_evidence_accuracy is not None else None),
        "n_claims": len(claims), "n_cited_documents": len(got_doc_ids), "n_gold": len(gold),
    }
