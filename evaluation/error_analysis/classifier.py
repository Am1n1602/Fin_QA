"""Rule-based classification of *why* a retrieval case failed (§6).

`classify()` takes metadata already resolved by `analyzer.py` -- it does no I/O itself, so
it can be unit-tested with plain fixtures. Rules are checked in priority order and the
first match wins; a case can plausibly show more than one symptom, but only the most
specific/diagnostic one is reported (mirrors how this codebase's verification/adjudication
modules already pick one verdict per claim rather than stacking labels).

Note on `MISSING_DOCUMENT`: within *this* benchmark, every non-adversarial case's gold
chunks are verified present in the corpus at dataset-build time (`retrieval_v21/build.py`)
-- so "the document doesn't exist at all" cannot literally be the reason a gold-bearing
case failed. The class stays in the taxonomy (§6 lists it, and it's the right label for a
production query log where gold may genuinely not exist) but `classify()` never returns it
for this dataset; the analyzer's report says so explicitly rather than silently omitting it.
"""
from __future__ import annotations

from dataclasses import dataclass

ERROR_CLASSES = (
    "NO_COMPANY_MATCH", "MULTI_HOP_FAILURE", "TABLE_RETRIEVAL_FAILURE", "WRONG_SECTION",
    "WRONG_PERIOD", "STALE_DOCUMENT", "CHUNK_BOUNDARY", "LEXICAL_MISS", "SEMANTIC_MISS",
    "MISSING_DOCUMENT", "INSUFFICIENT_CONTEXT",
)

_CHUNK_BOUNDARY_WINDOW = 2


@dataclass(frozen=True)
class ChunkMeta:
    """The subset of `document_chunks` (+`documents.is_superseded`) fields the classifier
    needs, for a gold chunk or a retrieved one alike."""
    chunk_id: int
    document_id: int
    company_id: int
    chunk_index: int
    section: str | None
    topic: str | None
    financial_year: int | None
    is_superseded: bool = False


def classify(
    *,
    intent: str,
    had_company: bool,
    company_resolved: bool,
    gold: list[ChunkMeta],
    top_hits: list[ChunkMeta],
    lexical_found: bool | None = None,
    vector_found: bool | None = None,
) -> str:
    if had_company and not company_resolved:
        return "NO_COMPANY_MATCH"

    if intent == "multi_hop":
        return "MULTI_HOP_FAILURE"

    gold_topics = {g.topic for g in gold}
    if "table" in gold_topics and not any(h.topic == "table" for h in top_hits):
        return "TABLE_RETRIEVAL_FAILURE"

    gold_companies = {g.company_id for g in gold}
    gold_sections = {g.section for g in gold if g.section}
    same_company_hits = [h for h in top_hits if h.company_id in gold_companies]

    if same_company_hits and gold_sections and not any(h.section in gold_sections for h in same_company_hits):
        return "WRONG_SECTION"

    gold_fys = {g.financial_year for g in gold if g.financial_year}
    if gold_fys:
        section_matches = [h for h in same_company_hits if not gold_sections or h.section in gold_sections]
        if section_matches and not any(h.financial_year in gold_fys for h in section_matches
                                       if h.financial_year is not None):
            return "WRONG_PERIOD"

    if top_hits and top_hits[0].is_superseded:
        return "STALE_DOCUMENT"

    gold_docs_and_idx = {(g.document_id, g.chunk_index) for g in gold}
    for h in top_hits:
        for doc_id, idx in gold_docs_and_idx:
            if h.document_id == doc_id and abs(h.chunk_index - idx) <= _CHUNK_BOUNDARY_WINDOW:
                return "CHUNK_BOUNDARY"

    if vector_found is True and lexical_found is False:
        return "LEXICAL_MISS"
    if lexical_found is True and vector_found is False:
        return "SEMANTIC_MISS"

    return "INSUFFICIENT_CONTEXT"
