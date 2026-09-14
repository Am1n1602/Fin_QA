"""HybridRetriever (§16-17): metadata pre-filter -> BM25 + vector -> RRF -> section
weighting -> rerank -> top-k.

modes: 'lexical' (BM25 only), 'vector' (dense only), 'hybrid' (both, fused). Falls back
to lexical when a vector index / embedder is not wired.

`retrieve(..., intent=None)` (§15): when `intent` is given, each candidate's fused score is
multiplied by its section's *and* its topic's configured weight
(`finqa_v2/retrieval/section_weights.yaml`) before the top-k cut -- e.g. a `causal` query's
`mda`/`earnings_call` chunks rank higher, boilerplate `cover_letter` chunks rank lower, and
a `numeric` query's `topic='table'` chunks rank higher, regardless of section. `intent=None`
(every caller that predates §15) skips the step entirely, so existing behavior is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.models import DocumentChunk
from finqa_v2.retrieval.filters import compile_filter
from finqa_v2.retrieval.fuse import reciprocal_rank_fusion
from finqa_v2.retrieval.fusion_weights import get_fusion_weights as _fusion_weights
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.retrieval.rerank import IdentityReranker
from finqa_v2.retrieval.section_weights import get_topic_weight as _topic_weight
from finqa_v2.retrieval.section_weights import get_weight as _section_weight

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
                 rerank: bool = True, intent: str | None = None,
                 lexical_query: str | None = None,
                 weighted_fusion: bool = False) -> list[RetrievedChunk]:
        """`lexical_query` (§11, default None -- every pre-existing caller keeps `query`
        for BOTH legs, unchanged): when given, the BM25 leg searches `lexical_query`
        (e.g. a synonym-expanded string from `finqa_v2.planner.terminology.
        expand_lexical_query`) while the dense/vector leg still embeds `query` as-is --
        a natural-language question and a keyword-expanded BM25 query serve their
        respective retrieval methods differently.

        `weighted_fusion` (§16, default False -- every pre-existing caller keeps plain
        unweighted RRF, unchanged): when True, the lexical/vector legs are weighted per
        `finqa_v2.retrieval.fusion_weights.get_fusion_weights(intent)` before summing rank
        scores, instead of the equal 1.0/1.0 weight plain RRF uses."""
        if mode == "hybrid" and "hybrid" not in self.modes:
            mode = "lexical"
        if mode not in ("lexical", "vector", "hybrid"):
            raise ValueError(f"unknown mode {mode!r}")
        keep = compile_filter(filters)
        bm25_query = lexical_query if lexical_query is not None else query

        lex_hits = self._bm25.search(bm25_query, candidate_k, filters=filters) if mode in ("lexical", "hybrid") else []
        lex_ids = [h.chunk_id for h in lex_hits]
        lex_score = {h.chunk_id: h.score for h in lex_hits}

        vec_ids = self._vector_hits(query, candidate_k, keep) if mode in ("vector", "hybrid") else []

        fusion_weights = _fusion_weights(intent) if weighted_fusion and mode == "hybrid" else None

        if mode == "lexical":
            ordered = lex_ids
        elif mode == "vector":
            ordered = vec_ids
        else:
            fused = reciprocal_rank_fusion([lex_ids, vec_ids], weights=fusion_weights)
            ordered = [cid for cid, _ in fused]
        rrf_score = {cid: s for cid, s in fused} if mode == "hybrid" else {}

        candidates = ordered[:candidate_k]
        chunks = self._load_chunks(candidates)
        candidates = [cid for cid in candidates if cid in chunks]

        section_weight: dict[int, float] = {}
        if intent is not None and candidates:
            base_score = {cid: 1.0 / (pos + 1) for pos, cid in enumerate(candidates)}
            section_weight = {
                cid: _section_weight(intent, chunks[cid].section) * _topic_weight(intent, chunks[cid].topic)
                for cid in candidates
            }
            candidates = sorted(candidates, key=lambda cid: base_score[cid] * section_weight[cid], reverse=True)

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
                    "section_weight": section_weight.get(cid),
                    "rerank": rerank_score.get(cid),
                },
            ))
        return out
