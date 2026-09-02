from __future__ import annotations

import re
import sqlite3

from rank_bm25 import BM25Okapi

from src.storage.db import get_chunks_by_ids
from src.indexing.faiss_index import DualFaissIndex

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    """Minimal tokenizer for BM25: lowercase, split on non-alphanumeric.
    No stemming/stopword removal -- deliberately simple for a first pass,
    per this project's convention of starting simple and refining once real
    retrieval quality can be measured (same approach as chunker.py's
    initial fixed-size strategy)."""
    return _TOKEN_PATTERN.findall(text.lower())


def retrieve(
    conn: sqlite3.Connection,
    index: DualFaissIndex,
    embedder,
    query: str,
    k: int = 5,
    company: str | None = None,
) -> list[dict]:
    """
    Pure semantic search (FAISS only). 
    """
    query_vector = embedder.embed([query])[0]
    raw_results = index.search(query_vector, k=k, company=company)
    if not raw_results:
        return []

    chunk_ids = [cid for cid, _ in raw_results]
    score_by_id = dict(raw_results)

    rows = get_chunks_by_ids(conn, chunk_ids)

    return [_row_to_dict(row, score_by_id[row["id"]]) for row in rows]


def _lexical_search(conn: sqlite3.Connection, query: str, company: str | None, top_n: int) -> list[int]:
    """
    Runs a fresh BM25 search over all chunk text in scope, built on the fly
    from SQLite.
    """
    if company:
        rows = conn.execute(
            "SELECT dc.id, dc.text FROM document_chunks dc "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE d.company_symbol = ? AND d.is_superseded = 0",
            (company,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT dc.id, dc.text FROM document_chunks dc "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE d.is_superseded = 0"
        ).fetchall()

    if not rows:
        return []

    chunk_ids = [r[0] for r in rows]
    tokenized_corpus = [_tokenize(r[1]) for r in rows]
    bm25 = BM25Okapi(tokenized_corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked_indices = sorted(range(len(chunk_ids)), key=lambda i: scores[i], reverse=True)
    return [chunk_ids[i] for i in ranked_indices[:top_n]]


def _bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    return set(zip(tokens, tokens[1:]))


def _phrase_overlap_search(conn: sqlite3.Connection, query: str, company: str | None, top_n: int) -> list[int]:
    """
    Ranks chunks by how many of the QUERY's word bigrams appear as
    consecutive words in the chunk -- i.e. rewards phrase proximity, not
    just bag-of-words term presence.
    """
    query_bigrams = _bigrams(_tokenize(query))
    if not query_bigrams:
        return []

    if company:
        rows = conn.execute(
            "SELECT dc.id, dc.text FROM document_chunks dc "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE d.company_symbol = ? AND d.is_superseded = 0",
            (company,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT dc.id, dc.text FROM document_chunks dc "
            "JOIN documents d ON dc.document_id = d.id "
            "WHERE d.is_superseded = 0"
        ).fetchall()

    scored = []
    for chunk_id, text in rows:
        overlap = len(query_bigrams & _bigrams(_tokenize(text)))
        if overlap > 0:
            scored.append((chunk_id, overlap))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in scored[:top_n]]


def _reciprocal_rank_fusion(rankings: list[list[int]], k: int = 60) -> list[tuple[int, float]]:
    """
    Combines multiple rank-ordered id lists into one fused ranking, using
    Reciprocal Rank Fusion: score(id) = sum over each ranking containing id
    of 1/(k + rank). Standard, well-established technique for combining
    rankings on incompatible scales.
    Returns (id, fused_score) pairs sorted by fused_score descending.
    """
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)


def hybrid_retrieve(
    conn: sqlite3.Connection,
    index: DualFaissIndex,
    embedder,
    query: str,
    k: int = 5,
    company: str | None = None,
    candidate_pool_size: int = 50,
) -> list[dict]:
    """
    Semantic (FAISS) + lexical (BM25) search run in PARALLEL, fused via
    Reciprocal Rank Fusion -- not a rerank of FAISS's candidates only.
    """
    query_vector = embedder.embed([query])[0]
    semantic_results = index.search(query_vector, k=candidate_pool_size, company=company)
    semantic_ranked_ids = [cid for cid, _ in semantic_results]

    lexical_ranked_ids = _lexical_search(conn, query, company, top_n=candidate_pool_size)
    phrase_ranked_ids = _phrase_overlap_search(conn, query, company, top_n=candidate_pool_size)

    fused = _reciprocal_rank_fusion([semantic_ranked_ids, lexical_ranked_ids, phrase_ranked_ids])[:k]
    if not fused:
        return []

    fused_ids = [cid for cid, _ in fused]
    score_by_id = dict(fused)

    rows = get_chunks_by_ids(conn, fused_ids)

    return [_row_to_dict(row, score_by_id[row["id"]]) for row in rows]


def reranked_retrieve(
    conn: sqlite3.Connection,
    index: DualFaissIndex,
    embedder,
    reranker,
    query: str,
    k: int = 5,
    company: str | None = None,
    candidate_pool_size: int = 30,
) -> list[dict]:
    """
    Two-stage retrieval: hybrid_retrieve() gathers a broad candidate pool
    (semantic + lexical + phrase-overlap fusion), then `reranker` (a
    CrossEncoderReranker from reranking/reranker.py) rescores each
    candidate jointly against the query and the final top-k is returned in
    THAT order.
    """
    candidates = hybrid_retrieve(conn, index, embedder, query, k=candidate_pool_size, company=company)
    if not candidates:
        return []
    reranked = reranker.rerank(query, candidates)
    return reranked[:k]


def _row_to_dict(row, score: float) -> dict:
    return {
        "score": score,
        "text": row["text"],
        "company": row["company_symbol"],
        "title": row["title"],
        "source": row["source"],
        "period": row["period"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
        "section": row["section"],
        "local_path": row["local_path"],
    }