"""Binary-relevance nDCG@k over a list of per-rank relevance flags (1 = relevant, 0 =
not), same formula `evaluation/evaluators/retrieval.py` already uses -- kept here as a
standalone, reusable function per the v2.1 roadmap's §34 evaluation/metrics/ layout."""
from __future__ import annotations

import math


def dcg_at_k(relevances: list[int], k: int) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(relevances[:k]))


def ndcg_at_k(relevances: list[int], k: int) -> float:
    ideal = sorted(relevances, reverse=True)
    idcg = dcg_at_k(ideal, k)
    return dcg_at_k(relevances, k) / idcg if idcg else 0.0


def mean_ndcg_at_k(relevance_lists: list[list[int]], k: int) -> float:
    if not relevance_lists:
        return 0.0
    return sum(ndcg_at_k(rels, k) for rels in relevance_lists) / len(relevance_lists)
