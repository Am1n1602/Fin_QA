"""Document tools (§19): search_documents, get_document_section, get_source."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from database.v2.evidence import (
    EvidenceSet,
    citation_for_document,
    evidence_from_retrieved_chunk,
)


class _Search(BaseModel):
    query: str = Field(..., min_length=2)
    company: str | None = Field(None, description="NSE ticker to scope the search to")
    sections: list[str] | None = Field(None, description="restrict to these chunk sections")
    financial_year: int | None = None
    k: int = Field(5, ge=1, le=20)
    mode: Literal["lexical", "vector", "hybrid"] = "hybrid"


class _Section(BaseModel):
    company: str
    section: str = Field(..., description="e.g. auditors_report, segment_information, notes")
    financial_year: int | None = None
    limit: int = Field(8, ge=1, le=40)


class _Source(BaseModel):
    document_id: int
    page: int | None = None
    page_end: int | None = None
    section: str | None = None


def register(reg, repos, retriever) -> None:
    def _search(m: _Search):
        if retriever is None:
            raise RuntimeError("no retriever wired -- build the BM25 index and pass a HybridRetriever")
        co = repos.companies.resolve(m.company) if m.company else None
        filters = {}
        if co:
            filters["company_id"] = co.company_id
        if m.sections:
            filters["section"] = m.sections
        if m.financial_year:
            filters["financial_year"] = m.financial_year
        hits = retriever.retrieve(m.query, k=m.k, mode=m.mode, filters=filters or None)
        ws = EvidenceSet()
        for h in hits:
            evidence_from_retrieved_chunk(h, repos=repos, company=m.company, workspace=ws)
        return {"query": m.query, "mode": m.mode, "n": len(ws), "filters": filters}, ws.to_list()

    def _section(m: _Section):
        co = repos.companies.resolve(m.company)
        if co is None:
            raise LookupError(f"unknown company {m.company!r}")
        docs = repos.documents.for_company(co.company_id)
        if m.financial_year is not None:
            docs = [d for d in docs if d.financial_year == m.financial_year]
        ws = EvidenceSet()
        from database.v2.evidence.models import Evidence, EvidenceType

        n = 0
        for d in docs:
            for ch in repos.documents.chunks_for(d.document_id, section=m.section):
                if n >= m.limit:
                    break
                cite = citation_for_document(repos, d.document_id, page=ch.page_start,
                                             page_end=ch.page_end, section=ch.section)
                ws.add(Evidence(
                    evidence_id=f"sec-{d.document_id}-{ch.chunk_index}",
                    type=EvidenceType.DOCUMENT, text=ch.text, company=m.company,
                    company_id=co.company_id, document_id=d.document_id, page=ch.page_start,
                    section=ch.section, period=(f"FY{ch.financial_year}" if ch.financial_year else None),
                    confidence=0.6, citation=cite,
                ))
                n += 1
        return {"company": m.company, "section": m.section, "n": len(ws)}, ws.to_list()

    def _source(m: _Source):
        cite = citation_for_document(repos, m.document_id, page=m.page, page_end=m.page_end,
                                     section=m.section)
        return cite.to_dict()

    reg.add("search_documents",
            "Hybrid retrieval over filing text. Optionally scope by company / sections / year.",
            _Search, _search)
    reg.add("get_document_section",
            "All chunks of one section (e.g. auditors_report, segment_information) for a company.",
            _Section, _section)
    reg.add("get_source", "Citation details (title, page, section, period) for a document.",
            _Source, _source)
