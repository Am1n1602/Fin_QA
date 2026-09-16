"""tokenize / RRF / evaluate math."""
from __future__ import annotations

import unittest

from finqa_v2.retrieval.evaluate import _relevant
from finqa_v2.retrieval.fuse import fuse_ids, reciprocal_rank_fusion
from finqa_v2.retrieval.tokenize import tokenize


class TestTokenize(unittest.TestCase):
    def test_basics(self):
        # "for"/"was" are stopwords; "1" from "27.1" is dropped as a 1-char token
        self.assertEqual(tokenize("The EBITDA margin for FY2026 revenue 27.1 percent"),
                         ["ebitda", "margin", "fy2026", "revenue", "27", "percent"])

    def test_stopwords_and_short(self):
        self.assertNotIn("the", tokenize("the a an of to in"))
        self.assertEqual(tokenize("a I x"), [])

    def test_none_safe(self):
        self.assertEqual(tokenize(None), [])


class TestRRF(unittest.TestCase):
    def test_fusion_prefers_consensus(self):
        lex = [10, 20, 30]
        vec = [20, 40, 10]
        fused = fuse_ids([lex, vec])
        self.assertEqual(fused[0], 20)                # rank 2 + rank 1 -> best
        self.assertEqual(set(fused), {10, 20, 30, 40})

    def test_scores_monotonic(self):
        scored = reciprocal_rank_fusion([[1, 2, 3]])
        self.assertGreater(scored[0][1], scored[1][1])
        self.assertGreater(scored[1][1], scored[2][1])

    def test_empty(self):
        self.assertEqual(fuse_ids([[], []]), [])

    def test_weights_none_is_unchanged_from_omitting_the_argument(self):
        lex, vec = [10, 20, 30], [20, 40, 10]
        self.assertEqual(reciprocal_rank_fusion([lex, vec]),
                         reciprocal_rank_fusion([lex, vec], weights=None))

    def test_equal_weights_match_plain_rrf(self):
        lex, vec = [10, 20, 30], [20, 40, 10]
        self.assertEqual(reciprocal_rank_fusion([lex, vec]),
                         reciprocal_rank_fusion([lex, vec], weights=[1.0, 1.0]))

    def test_weighting_one_leg_to_zero_ignores_it(self):
        # a zero-weighted leg contributes 0 score, not removal -- 40 (vec-only) still
        # appears, but always last since its score is 0 while every lex doc scores > 0.
        lex, vec = [10, 20, 30], [20, 40, 10]
        only_lex = reciprocal_rank_fusion([lex, vec], weights=[1.0, 0.0])
        self.assertEqual([cid for cid, _ in only_lex], [10, 20, 30, 40])
        self.assertEqual(only_lex[-1][1], 0.0)

    def test_heavier_leg_can_flip_the_winner(self):
        lex, vec = [10, 20], [20, 10]   # tied under equal weight (both rank-1+rank-2)
        equal = reciprocal_rank_fusion([lex, vec])
        self.assertEqual(equal[0][1], equal[1][1])
        vector_heavy = reciprocal_rank_fusion([lex, vec], weights=[0.5, 2.0])
        self.assertEqual(vector_heavy[0][0], 20)   # vec's rank-1 pick now wins

    def test_mismatched_weights_length_raises(self):
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([[1, 2], [3, 4]], weights=[1.0])


class _C:
    def __init__(self, company_id, section, text):
        self.company_id, self.section, self.text = company_id, section, text


class TestRelevance(unittest.TestCase):
    def test_company_section_keyword(self):
        case = {"sections": ["notes"], "must_contain": ["dividend"]}
        self.assertTrue(_relevant(_C(3, "notes", "final dividend recommended"), case, 3))
        self.assertFalse(_relevant(_C(3, "notes", "final dividend recommended"), case, 9))  # wrong company
        self.assertFalse(_relevant(_C(3, "auditors_report", "final dividend"), case, 3))    # wrong section
        self.assertFalse(_relevant(_C(3, "notes", "no payout here"), case, 3))              # no keyword

    def test_no_constraints_is_relevant(self):
        self.assertTrue(_relevant(_C(1, "x", "anything"), {}, None))


if __name__ == "__main__":
    unittest.main()
