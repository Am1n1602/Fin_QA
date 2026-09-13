"""Recall@k over a first-relevant-rank list (1-based rank, or None if nothing relevant
was retrieved at all)."""
from __future__ import annotations


def recall_at_k(first_relevant_rank: int | None, k: int) -> int:
    return 1 if (first_relevant_rank is not None and first_relevant_rank <= k) else 0


def mean_recall_at_k(first_relevant_ranks: list[int | None], k: int) -> float:
    if not first_relevant_ranks:
        return 0.0
    return sum(recall_at_k(r, k) for r in first_relevant_ranks) / len(first_relevant_ranks)
