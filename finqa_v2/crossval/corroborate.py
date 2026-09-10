"""§23 step: does the filing text actually contain the management statement?

Retrieval scoped to the company (+ FY when known). A passage is 'stated' when it
overlaps the claim's wording; a nearby negation cue ('not', 'despite', 'offset by')
flips it to 'contradicted'. No LLM.
"""
from __future__ import annotations

import re

from finqa_v2.evidence import evidence_from_retrieved_chunk
from finqa_v2.hypothesis.validate import lexical_overlap

_MIN_OVERLAP = 2
_MIN_CONF = 0.40
_NEG = re.compile(r"\b(not|no|without|despite|however|offset by|partially offset|"
                  r"declined|weak(er)?|headwind|drag)\b", re.I)


def corroborate_in_docs(retriever, repos, ticker, claim, fy, *, workspace=None, k=6):
    """-> (doc_status, [evidence_id, ...]). doc_status in {'stated','absent','contradicted'}."""
    if retriever is None:
        return "absent", []
    co = repos.companies.resolve(ticker)
    filters = {}
    if co is not None:
        filters["company_id"] = co.company_id
    if fy:
        filters["financial_year"] = fy

    query = " ".join(x for x in (claim.subject or "", claim.mechanism or "", claim.raw) if x)
    try:
        hits = retriever.retrieve(query, k=k, filters=filters or None)
    except Exception:
        # retry without the FY filter (thin corpus)
        try:
            hits = retriever.retrieve(query, k=k, filters={"company_id": co.company_id} if co else None)
        except Exception:
            return "absent", []

    probe = " ".join(x for x in (claim.raw, claim.mechanism or "") if x)
    stated_ids, contra_ids, kept = [], [], []
    for h in hits:
        ev = evidence_from_retrieved_chunk(h, repos=repos, company=ticker, workspace=workspace)
        ov = lexical_overlap(probe, ev.text)
        if ov < _MIN_OVERLAP or (ev.confidence or 0) < _MIN_CONF:
            continue
        eid = workspace.add(ev) if workspace is not None else ev.evidence_id  # canonical id
        kept.append(eid)
        if _negated_near(ev.text, claim):
            contra_ids.append(eid)
        else:
            stated_ids.append(eid)
        if len(kept) >= 3:
            break

    if stated_ids:
        return "stated", stated_ids + [i for i in contra_ids if i not in stated_ids]
    if contra_ids:
        return "contradicted", contra_ids
    return "absent", []


def _negated_near(text: str, claim) -> bool:
    """A negation cue in the same sentence as the claim's mechanism / subject word."""
    key = (claim.mechanism or claim.subject or "").split()
    key = key[-1].lower() if key else ""
    if not key:
        return False
    for sent in re.split(r"(?<=[.!?])\s+", text or ""):
        if key in sent.lower() and _NEG.search(sent):
            return True
    return False
