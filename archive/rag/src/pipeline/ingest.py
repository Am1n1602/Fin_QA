from __future__ import annotations

import sqlite3

from src.extraction.pdf_extractor import extract_pdf_text
from src.chunking.chunker import chunk_extraction_result
from src.storage.db import find_document_by_sha256, insert_document, insert_chunks
from src.indexing.faiss_index import DualFaissIndex


def ingest_document(
    conn: sqlite3.Connection,
    index: DualFaissIndex,
    embedder,
    company: str,
    title: str,
    local_path: str,
    sha256: str,
    source: str | None = None,
    period: str | None = None,
    also_known_as: list[str] | None = None,
    chunk_size: int = 1000,
    overlap: int = 150,
    batch_size: int = 32,
) -> dict:
    """
    Runs one document through extraction -> chunking -> embedding -> DB ->
    FAISS. Returns a status dict rather than raising on ordinary failure
    modes (extraction failure, zero chunks) -- those are expected outcomes. 
    Returns one of:
        {"status": "already_ingested", "document_id": int}
        {"status": "extraction_failed", "error": str}
        {"status": "zero_chunks", "document_id": int}
        {"status": "ingested", "document_id": int, "chunk_count": int}
    """
    existing = find_document_by_sha256(conn, sha256)
    if existing is not None:
        return {"status": "already_ingested", "document_id": existing["id"]}

    result = extract_pdf_text(local_path, known_sha256=sha256)
    if not result.ok:
        return {"status": "extraction_failed", "error": result.error}

    cr = chunk_extraction_result(result, chunk_size=chunk_size, overlap=overlap)

    document_id = insert_document(
        conn, company_symbol=company, title=title, sha256_hash=sha256,
        source=source, also_known_as=also_known_as, period=period,
        local_path=local_path, page_count=result.page_count,
    )

    if not cr.chunks:
        return {"status": "zero_chunks", "document_id": document_id}

    chunk_dicts = [
        {"chunk_index": c.chunk_index, "page_start": c.page_start, "page_end": c.page_end,
         "section": c.section, "text": c.text, "char_count": c.char_count}
        for c in cr.chunks
    ]
    chunk_ids = insert_chunks(conn, document_id, chunk_dicts)

    texts = [c.text for c in cr.chunks]
    vectors = embedder.embed(texts, batch_size=batch_size)
    index.add(company, chunk_ids, vectors)

    return {"status": "ingested", "document_id": document_id, "chunk_count": len(chunk_ids)}