"""Direct-SQL probes against `document_chunks` (v2.1 roadmap §5).

A retrieval benchmark needs literal, verified `gold_chunks` -- not a templated question
that merely sounds plausible. Every probe here runs a real query against the actual
corpus (`database/data/finqa_v2.db`) and returns only chunks that are genuinely there;
`build.py` keeps a candidate question only when its probe (or, for adversarial/no-evidence
items, its *absence* of hits) is confirmed this way.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkHit:
    chunk_id: int
    company_id: int
    document_id: int
    section: str | None
    document_type: str | None
    topic: str | None
    financial_year: int | None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def probe(
    conn: sqlite3.Connection,
    *,
    company_id: int | None = None,
    sections: list[str] | None = None,
    document_types: list[str] | None = None,
    topics: list[str] | None = None,
    keyword: str | None = None,
    financial_year: int | None = None,
    limit: int = 5,
    prefer_recent: bool = False,
) -> list[ChunkHit]:
    """Return up to `limit` real `document_chunks` rows matching every given filter.

    `keyword` matches case-insensitively as a substring of chunk text -- SQLite's LIKE is
    already ASCII case-insensitive, so no extra lower()/collation handling is needed.

    `prefer_recent=False` (default) orders by `chunk_id` -- roughly the order documents
    were ingested in, which for this corpus is roughly chronological-ASCENDING (oldest
    filings first). That default silently picked stale gold for period-unconstrained
    "what is X's current Y" questions once a company had several years of history: the
    real answer a system should give is the LATEST filing, but gold could be an older
    one. `prefer_recent=True` orders `financial_year DESC` (nulls last) first, so gold
    for categories whose real answer is "the current value" (build.py picks which
    categories) reflects the most recently filed matching chunk instead."""
    where: list[str] = []
    params: list = []
    if company_id is not None:
        where.append("company_id = ?")
        params.append(company_id)
    if financial_year is not None:
        where.append("financial_year = ?")
        params.append(financial_year)
    for column, values in (("section", sections), ("document_type", document_types), ("topic", topics)):
        if values:
            placeholders = ",".join("?" for _ in values)
            where.append(f"{column} IN ({placeholders})")
            params.extend(values)
    if keyword:
        where.append("text LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(keyword)}%")
    clause = " AND ".join(where) if where else "1=1"
    order = "(financial_year IS NULL), financial_year DESC, chunk_id" if prefer_recent else "chunk_id"
    sql = (
        "SELECT chunk_id, company_id, document_id, section, document_type, topic, financial_year "
        f"FROM document_chunks WHERE {clause} ORDER BY {order} LIMIT ?"
    )
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        ChunkHit(
            chunk_id=r[0], company_id=r[1], document_id=r[2],
            section=r[3], document_type=r[4], topic=r[5], financial_year=r[6],
        )
        for r in rows
    ]


def distinct_document_types(conn: sqlite3.Connection, *, company_id: int, keyword: str) -> list[str]:
    """document_types among chunks that contain `keyword` for one company -- used by the
    cross_document category to require evidence spanning more than one document type."""
    rows = conn.execute(
        "SELECT DISTINCT document_type FROM document_chunks "
        "WHERE company_id = ? AND text LIKE ? ESCAPE '\\' AND document_type IS NOT NULL",
        (company_id, f"%{_escape_like(keyword)}%"),
    ).fetchall()
    return [r[0] for r in rows]
