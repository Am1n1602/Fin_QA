"""HybridRetriever (§16-17): metadata pre-filter -> BM25 + vector -> RRF -> rerank -> top-k.

modes: 'lexical' (BM25 only), 'vector' (dense only), 'hybrid' (both, fused). Falls back
to lexical when a vector index / embedder is not wired.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.models import DocumentChunk
from finqa_v2.retrieval.filters import compile_filter
from finqa_v2.retrieval.fuse import reciprocal_rank_fusion
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.retrieval.rerank import IdentityReranker

_META_KEYS = ("company_id", "financial_year", "document_type", "section", "segment", "topic")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk: DocumentChunk
    rank: int
    scores: dict = field(default_factory=dict)

    def citation(self) -> str:
        c = self.chunk
        pages = f"p{c.page_start}" if c.page_start == c.page_end else f"p{c.page_start}-{c.page_end}"
        sect = f", {c.section}" if c.section else ""
        return f"doc#{c.document_id}{sect}, {pages}"


class HybridRetriever:
    def __init__(self, repos, *, bm25: BM25Index | None = None, vector=None,
                 embedder=None, reranker=None):
        self._repos = repos
        self._bm25 = bm25 if bm25 is not None else BM25Index.build(repos)
        self._vector = vector
        self._embedder = embedder
        self._reranker = reranker or IdentityReranker()
        # small: all chunk metadata by id (no text)
        rows = repos.connection.execute(
            f"SELECT chunk_id, {', '.join(_META_KEYS)} FROM document_chunks"
        ).fetchall()
        self._meta = {r["chunk_id"]: {k: r[k] for k in _META_KEYS} for r in rows}

    # ------------------------------------------------------------------ #
    @property
    def modes(self) -> tuple[str, ...]:
        base = ("lexical",)
        if self._vector is not None and getattr(self._vector, "available", False) and self._embedder is not None:
            return base + ("vector", "hybrid")
        return base

    def _load_chunks(self, chunk_ids: list[int]) -> dict[int, DocumentChunk]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        rows = self._repos.connection.execute(
            f"SELECT * FROM document_chunks WHERE chunk_id IN ({marks})", chunk_ids
        ).fetchall()
        from finqa_v2.sqlite.repo import _row_chunk

        return {r["chunk_id"]: _row_chunk(r) for r in rows}

    def _vector_hits(self, query: str, candidate_k: int, keep) -> list[int]:
        if "vector" not in self.modes:
            return []
        qv = self._embedder.encode([query])
        hits = self._vector.search(qv, candidate_k * 3)[0]
        return [cid for cid, _ in hits if keep(self._meta.get(cid, {}))][:candidate_k]

    # ------------------------------------------------------------------ #
    def retrieve(self, query: str, *, k: int = 5, candidate_k: int = 30,
                 mode: str = "hybrid", filters: dict | None = None,
                 rerank: bool = True) -> list[RetrievedChunk]:
        if mode == "hybrid" and "hybrid" not in self.modes:
            mode = "lexical"
        if mode not in ("lexical", "vector", "hybrid"):
            raise ValueError(f"unknown mode {mode!r}")
        keep = compile_filter(filters)

        lex_hits = self._bm25.search(query, candidate_k, filters=filters) if mode in ("lexical", "hybrid") else []
        lex_ids = [h.chunk_id for h in lex_hits]
        lex_score = {h.chunk_id: h.score for h in lex_hits}

        vec_ids = self._vector_hits(query, candidate_k, keep) if mode in ("vector", "hybrid") else []

        if mode == "lexical":
            ordered = lex_ids
        elif mode == "vector":
            ordered = vec_ids
        else:
            ordered = [cid for cid, _ in reciprocal_rank_fusion([lex_ids, vec_ids])]
        rrf_score = {cid: s for cid, s in reciprocal_rank_fusion([lex_ids, vec_ids])} if mode == "hybrid" else {}

        candidates = ordered[:candidate_k]
        chunks = self._load_chunks(candidates)
        candidates = [cid for cid in candidates if cid in chunks]

        rerank_score: dict[int, float] = {}
        if rerank and candidates and not getattr(self._reranker, "trivial", False):
            rr = self._reranker.score(query, [chunks[cid].text for cid in candidates])
            rerank_score = dict(zip(candidates, rr))
            candidates = [cid for cid, _ in sorted(zip(candidates, rr), key=lambda x: x[1], reverse=True)]

        out: list[RetrievedChunk] = []
        for i, cid in enumerate(candidates[:k], start=1):
            out.append(RetrievedChunk(
                chunk=chunks[cid], rank=i,
                scores={
                    "lexical": lex_score.get(cid),
                    "rrf": rrf_score.get(cid),
                    "rerank": rerank_score.get(cid),
                },
            ))
        return out
