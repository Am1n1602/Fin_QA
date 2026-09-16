"""Metadata-enriched embedding text (§8). Prepends structured metadata (company, period,
document type, section, page) to a chunk's text -- but only for EMBEDDING INPUT. The
original `document_chunks.text` (used for citations, display, BM25 lexical search) is
never touched; this function's output is only ever passed to an embedder's `.encode()`,
never stored back into the corpus. See `VectorIndex.build(..., text_fn=...)`.
"""
from __future__ import annotations


def build_embedding_text(
    *,
    text: str,
    company_name: str | None = None,
    financial_year: int | None = None,
    document_type: str | None = None,
    section: str | None = None,
    page_start: int | None = None,
) -> str:
    """`text` unchanged when no metadata is available (never returns an empty header)."""
    lines: list[str] = []
    if company_name:
        lines.append(f"Company: {company_name}")
    if financial_year:
        lines.append(f"Period: FY{financial_year}")
    if document_type:
        lines.append(f"Document: {document_type}")
    if section:
        lines.append(f"Section: {section}")
    if page_start:
        lines.append(f"Page: {page_start}")
    if not lines:
        return text
    return "\n".join(lines) + "\n\n" + text


def from_row(row) -> str:
    """Adapter for the sqlite row shape `VectorIndex.build()` selects -- see its
    `text_fn` parameter."""
    return build_embedding_text(
        text=row["text"], company_name=row["company_name"],
        financial_year=row["financial_year"], document_type=row["document_type"],
        section=row["section"], page_start=row["page_start"],
    )
