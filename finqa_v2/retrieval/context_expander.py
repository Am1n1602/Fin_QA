"""Neighbor context expansion (§17): after the retriever picks its final top-k, pull in
each selected chunk's immediate document neighbors (prev/next by `chunk_index`) so a fact
that spans a chunk boundary isn't silently cut off by the chunk size -- Phase 2's
CHUNK_BOUNDARY error category. `window=0` (default, every pre-existing caller) is a no-op.

Neighbors carry the SAME rank as the chunk that pulled them in (they aren't independently
ranked against the query) and a `scores["neighbor_of"]` marker instead of retrieval scores,
so downstream evidence-building can tell an anchor chunk from a context chunk if it ever
needs to. Deduplicated by `chunk_id` -- a neighbor that's already a top-k hit in its own
right is never added twice.
"""
from __future__ import annotations


def expand_with_neighbors(hits: list, repos, *, window: int = 0) -> list:
    if window <= 0 or not hits:
        return hits
    from finqa_v2.retrieval.retriever import RetrievedChunk
    from finqa_v2.sqlite.repo import _row_chunk

    conn = repos.connection
    out = list(hits)
    seen = {h.chunk.chunk_id for h in hits}
    for h in hits:
        ch = h.chunk
        lo, hi = ch.chunk_index - window, ch.chunk_index + window
        rows = conn.execute(
            "SELECT * FROM document_chunks WHERE document_id = ? AND chunk_index BETWEEN ? AND ? "
            "AND chunk_index != ? ORDER BY chunk_index",
            (ch.document_id, lo, hi, ch.chunk_index),
        ).fetchall()
        for r in rows:
            if r["chunk_id"] in seen:
                continue
            seen.add(r["chunk_id"])
            out.append(RetrievedChunk(chunk=_row_chunk(r), rank=h.rank,
                                      scores={"neighbor_of": ch.chunk_id}))
    return out
