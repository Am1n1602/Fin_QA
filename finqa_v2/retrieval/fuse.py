"""Reciprocal Rank Fusion (§16). score(d) = sum_r w_r / (k + rank_r(d)), rank 1-based."""
from __future__ import annotations

from typing import Iterable, Sequence


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], *, k: int = 60,
                           weights: Sequence[float] | None = None) -> list[tuple[int, float]]:
    """`weights` (§16, default None -- every pre-existing caller keeps equal 1.0 weight per
    ranking, unchanged): one multiplier per entry in `rankings`, e.g. [lexical_weight,
    vector_weight] to make Weighted/query-dependent RRF favor one leg over the other."""
    if weights is not None and len(weights) != len(rankings):
        raise ValueError(f"weights length {len(weights)} != rankings length {len(rankings)}")
    scores: dict[int, float] = {}
    for i, ranking in enumerate(rankings):
        w = weights[i] if weights is not None else 1.0
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + w / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def fuse_ids(rankings: Iterable[Sequence[int]], *, k: int = 60) -> list[int]:
    return [doc_id for doc_id, _ in reciprocal_rank_fusion(list(rankings), k=k)]
