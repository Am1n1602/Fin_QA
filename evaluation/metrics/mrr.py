"""Mean Reciprocal Rank over a first-relevant-rank list (1-based rank, or None)."""
from __future__ import annotations


def reciprocal_rank(first_relevant_rank: int | None) -> float:
    return 1.0 / first_relevant_rank if first_relevant_rank else 0.0


def mean_reciprocal_rank(first_relevant_ranks: list[int | None]) -> float:
    if not first_relevant_ranks:
        return 0.0
    return sum(reciprocal_rank(r) for r in first_relevant_ranks) / len(first_relevant_ranks)
