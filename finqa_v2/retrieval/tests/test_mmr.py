import unittest

import numpy as np

from finqa_v2.retrieval.mmr import mmr_select


class MmrSelect(unittest.TestCase):
    def test_empty_candidates_returns_empty(self):
        self.assertEqual(mmr_select([], {}, {}, k=5), [])

    def test_empty_vectors_falls_back_to_plain_top_k(self):
        self.assertEqual(mmr_select([1, 2, 3, 4], {1: 0.9, 2: 0.8, 3: 0.7, 4: 0.6}, {}, k=2),
                         [1, 2])

    def test_k_larger_than_candidates_returns_all(self):
        vectors = {1: np.array([1.0, 0.0]), 2: np.array([0.0, 1.0])}
        out = mmr_select([1, 2], {1: 1.0, 2: 0.5}, vectors, k=10)
        self.assertEqual(set(out), {1, 2})

    def test_pure_relevance_when_lambda_is_one(self):
        # two near-identical (redundant) top candidates and one distinct low-relevance
        # one -- lambda=1 ignores diversity entirely, so plain relevance order wins.
        vectors = {1: np.array([1.0, 0.0]), 2: np.array([1.0, 0.0]), 3: np.array([0.0, 1.0])}
        relevance = {1: 1.0, 2: 0.9, 3: 0.1}
        out = mmr_select([1, 2, 3], relevance, vectors, k=2, lam=1.0)
        self.assertEqual(out, [1, 2])

    def test_diversity_promotes_a_distinct_lower_relevance_candidate(self):
        # 1 and 2 are near-duplicates (same vector); 3 is orthogonal (fully distinct) but
        # scores lower on raw relevance. A low lambda should still pick 3 over the
        # redundant 2 once 1 has already been selected.
        vectors = {1: np.array([1.0, 0.0]), 2: np.array([1.0, 0.0]), 3: np.array([0.0, 1.0])}
        relevance = {1: 1.0, 2: 0.95, 3: 0.5}
        out = mmr_select([1, 2, 3], relevance, vectors, k=2, lam=0.3)
        self.assertEqual(out, [1, 3])

    def test_missing_vector_never_penalized_by_diversity(self):
        # candidate 2 has no vector at all -- it should still be selectable purely on
        # relevance, contributing similarity 0 rather than crashing or being excluded.
        vectors = {1: np.array([1.0, 0.0])}
        relevance = {1: 0.5, 2: 0.9}
        out = mmr_select([1, 2], relevance, vectors, k=2, lam=0.5)
        self.assertEqual(set(out), {1, 2})

    def test_flat_relevance_does_not_divide_by_zero(self):
        vectors = {1: np.array([1.0, 0.0]), 2: np.array([0.0, 1.0])}
        out = mmr_select([1, 2], {1: 0.5, 2: 0.5}, vectors, k=2, lam=0.5)
        self.assertEqual(set(out), {1, 2})

    def test_result_never_exceeds_k(self):
        vectors = {i: np.array([float(i), 1.0]) for i in range(5)}
        relevance = {i: 1.0 / (i + 1) for i in range(5)}
        out = mmr_select(list(range(5)), relevance, vectors, k=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(len(set(out)), 3)


if __name__ == "__main__":
    unittest.main()
