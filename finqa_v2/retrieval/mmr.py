"""Maximal Marginal Relevance (§18): after reranking (or the base fused ranking, when
reranking is off/unavailable), greedily re-select the final top-k from the candidate pool
to trade relevance against diversity, so near-duplicate chunks don't crowd out distinct
evidence in the final context.

    MMR(d) = lambda * relevance(d) - (1 - lambda) * max_{d' in selected} sim(d, d')

`relevance` is min-max normalized into [0, 1] internally so it's on the same scale as
cosine similarity (also [0, 1] for the row-normalized vectors this project stores) --
callers can pass raw RRF/rerank/BM25 scores as-is regardless of their native range.
"""
from __future__ import annotations


def mmr_select(candidates: list[int], relevance: dict[int, float], vectors: dict, *,
               k: int, lam: float = 0.7) -> list[int]:
    """Greedy MMR over `candidates` (assumed already ranked by `relevance`, highest
    first -- that order only matters as the fallback when `vectors` is empty). A
    candidate missing from `vectors` never contributes to or is penalized by the
    diversity term (treated as similarity 0 to everything), so it can still be selected
    on relevance alone. Returns `candidates[:k]` unchanged if `vectors` is empty --
    nothing to diversify against."""
    if not candidates:
        return []
    if not vectors:
        return candidates[:k]

    vals = [relevance.get(cid, 0.0) for cid in candidates]
    lo, hi = min(vals), max(vals)

    def _norm(cid: int) -> float:
        v = relevance.get(cid, 0.0)
        return (v - lo) / (hi - lo) if hi > lo else 1.0

    selected: list[int] = []
    pool = list(candidates)
    while pool and len(selected) < k:
        best_id, best_score = None, None
        for cid in pool:
            if selected and cid in vectors:
                max_sim = max((float(vectors[cid] @ vectors[s]) for s in selected if s in vectors),
                              default=0.0)
            else:
                max_sim = 0.0
            score = lam * _norm(cid) - (1 - lam) * max_sim
            if best_score is None or score > best_score:
                best_id, best_score = cid, score
        selected.append(best_id)
        pool.remove(best_id)
    return selected
