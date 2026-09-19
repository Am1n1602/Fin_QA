"""Optional metadata header prepended to a chunk's text before embedding.

Short, number-dense chunks (a table row, a one-line segment fact) lose exactly the
context -- which company, period, section -- a dense embedder needs to place them near
a natural-language question. This restores that context at embed time only:
`document_chunks.text` itself is never mutated, and lexical (BM25) search is unaffected
(it already gets company/period/section via metadata pre-filtering upstream).
"""
from __future__ import annotations


def build_embedding_text(text: str, *, company: str | None = None,
                          financial_year: int | None = None,
                          document_type: str | None = None,
                          section: str | None = None,
                          page: int | None = None) -> str:
    """Header + blank line + original text. Falsy fields are omitted. No metadata at
    all -> text is returned unchanged."""
    parts = []
    if company:
        parts.append(company)
    if financial_year:
        parts.append(f"FY{financial_year}")
    if document_type:
        parts.append(str(document_type).replace("_", " "))
    if section:
        parts.append(str(section).replace("_", " "))
    if page:
        parts.append(f"page {page}")
    if not parts:
        return text
    return " | ".join(parts) + "\n\n" + text


def from_row(row) -> str:
    """Adapter for a `document_chunks` row joined with `companies.ticker` (see the
    query in `VectorIndex.build`'s `text_fn` usage)."""
    return build_embedding_text(
        row["text"],
        company=row["ticker"] if "ticker" in row.keys() else None,
        financial_year=row["financial_year"],
        document_type=row["document_type"],
        section=row["section"],
        page=row["page_start"],
    )
