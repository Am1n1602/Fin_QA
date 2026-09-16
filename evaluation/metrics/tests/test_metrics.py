import unittest

from evaluation.metrics.mrr import mean_reciprocal_rank, reciprocal_rank
from evaluation.metrics.ndcg import dcg_at_k, mean_ndcg_at_k, ndcg_at_k
from evaluation.metrics.recall import mean_recall_at_k, recall_at_k


class Recall(unittest.TestCase):
    def test_hit_within_k(self):
        self.assertEqual(recall_at_k(3, 5), 1)
        self.assertEqual(recall_at_k(5, 5), 1)

    def test_miss_beyond_k(self):
        self.assertEqual(recall_at_k(6, 5), 0)

    def test_none_is_a_miss(self):
        self.assertEqual(recall_at_k(None, 5), 0)

    def test_mean_over_several_cases(self):
        # ranks: hit@1, hit@3 (miss@1), total miss -> recall@1=1/3, recall@3=2/3
        ranks = [1, 3, None]
        self.assertAlmostEqual(mean_recall_at_k(ranks, 1), 1 / 3)
        self.assertAlmostEqual(mean_recall_at_k(ranks, 3), 2 / 3)

    def test_empty_list_is_zero_not_a_crash(self):
        self.assertEqual(mean_recall_at_k([], 5), 0.0)


class MRR(unittest.TestCase):
    def test_reciprocal_rank(self):
        self.assertEqual(reciprocal_rank(1), 1.0)
        self.assertEqual(reciprocal_rank(4), 0.25)
        self.assertEqual(reciprocal_rank(None), 0.0)

    def test_mean_reciprocal_rank(self):
        self.assertAlmostEqual(mean_reciprocal_rank([1, 2, None]), (1.0 + 0.5 + 0.0) / 3)

    def test_empty_list_is_zero(self):
        self.assertEqual(mean_reciprocal_rank([]), 0.0)


class NDCG(unittest.TestCase):
    def test_perfect_ranking_is_one(self):
        self.assertAlmostEqual(ndcg_at_k([1, 1, 0], 3), 1.0)

    def test_no_relevant_is_zero(self):
        self.assertEqual(ndcg_at_k([0, 0, 0], 3), 0.0)

    def test_worse_ranking_scores_lower_than_ideal(self):
        ideal = [1, 1, 0]
        worse = [0, 1, 1]
        self.assertLess(ndcg_at_k(worse, 3), ndcg_at_k(ideal, 3))

    def test_dcg_matches_hand_computation(self):
        # dcg = 1/log2(2) + 0/log2(3) + 1/log2(4) = 1.0 + 0 + 0.5
        self.assertAlmostEqual(dcg_at_k([1, 0, 1], 3), 1.5)

    def test_mean_ndcg(self):
        self.assertAlmostEqual(mean_ndcg_at_k([[1, 0], [0, 0]], 2), ndcg_at_k([1, 0], 2) / 2)

    def test_empty_list_is_zero(self):
        self.assertEqual(mean_ndcg_at_k([], 5), 0.0)


if __name__ == "__main__":
    unittest.main()
