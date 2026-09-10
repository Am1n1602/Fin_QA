"""Reciprocal Rank Fusion (§16). score(d) = sum_r 1 / (k + rank_r(d)), rank 1-based."""
from __future__ import annotations

from typing import Iterable, Sequence


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], *, k: int = 60) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def fuse_ids(rankings: Iterable[Sequence[int]], *, k: int = 60) -> list[int]:
    return [doc_id for doc_id, _ in reciprocal_rank_fusion(list(rankings), k=k)]
