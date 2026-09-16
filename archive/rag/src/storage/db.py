from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def get_connection(db_path: str | Path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def find_document_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM documents WHERE sha256_hash = ?", (sha256,)
    ).fetchone()


def insert_document(
    conn: sqlite3.Connection,
    company_symbol: str,
    title: str,
    sha256_hash: str,
    source: str | None = None,
    also_known_as: list[str] | None = None,
    period: str | None = None,
    local_path: str | None = None,
    page_count: int | None = None,
) -> int:
    """Inserts a new document row. Caller must check find_document_by_sha256()
    first -- this does NOT dedupe internally, since the caller (ingest.py)
    needs to know whether it's inserting new or skipping, not have that
    decision hidden inside a helper."""
    cursor = conn.execute(
        """INSERT INTO documents
           (company_symbol, source, title, also_known_as, period, sha256_hash,
            local_path, page_count, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            company_symbol, source, title,
            json.dumps(also_known_as) if also_known_as else None,
            period, sha256_hash, local_path, page_count,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def insert_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    chunks: list[dict],
) -> list[int]:
    """
    chunks: list of {"chunk_index", "page_start", "page_end", "section", "text", "char_count"}
    Returns the list of document_chunks.id values in the same order as input
    -- these are the ids to use as FAISS vector ids.
    """
    ids = []
    for c in chunks:
        cursor = conn.execute(
            """INSERT INTO document_chunks
               (document_id, chunk_index, page_start, page_end, section, text, char_count)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (document_id, c["chunk_index"], c["page_start"], c["page_end"],
             c.get("section"), c["text"], c["char_count"]),
        )
        ids.append(cursor.lastrowid)
    conn.commit()
    return ids


def get_chunks_by_ids(conn: sqlite3.Connection, chunk_ids: list[int]) -> list[sqlite3.Row]:
    """Fetch chunk rows (joined with their document) for a list of
    document_chunks.id values, e.g. after a FAISS search returns ids.
    Filters out chunks belonging to superseded documents."""
    if not chunk_ids:
        return []
    placeholders = ",".join("?" * len(chunk_ids))
    rows = conn.execute(
        f"""SELECT dc.*, d.company_symbol, d.title, d.source, d.period,
                   d.local_path, d.is_superseded
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE dc.id IN ({placeholders}) AND d.is_superseded = 0""",
        chunk_ids,
    ).fetchall()
    row_by_id = {r["id"]: r for r in rows}
    return [row_by_id[cid] for cid in chunk_ids if cid in row_by_id]