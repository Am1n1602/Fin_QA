"""tokenize / RRF / evaluate math."""
from __future__ import annotations

import unittest

from database.v2.retrieval.evaluate import _relevant
from database.v2.retrieval.fuse import fuse_ids, reciprocal_rank_fusion
from database.v2.retrieval.tokenize import tokenize


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
