"""Confidence heuristics."""
from __future__ import annotations

import unittest

from database.v2.evidence.confidence import (
    claim_confidence,
    document_confidence,
    fact_confidence,
    graph_confidence,
    ratio_confidence,
)
from database.v2.evidence.models import ClaimStatus


class TestEvidenceConfidence(unittest.TestCase):
    def test_fact(self):
        self.assertAlmostEqual(fact_confidence(), 0.98)
        self.assertAlmostEqual(fact_confidence(derived=True), 0.90)
        self.assertAlmostEqual(fact_confidence(review_flagged=True), 0.72)
        # review flag dominates
        self.assertAlmostEqual(fact_confidence(derived=True, review_flagged=True), 0.72)

    def test_ratio(self):
        self.assertAlmostEqual(ratio_confidence(), 0.90)
        self.assertLess(ratio_confidence(review_flagged=True), 0.90)
        self.assertLess(ratio_confidence(missing_optional=True), 0.90)

    def test_document_bands(self):
        for kw in (
            {"rerank_score": 8.0}, {"rerank_score": -8.0},
            {"rrf_score": 0.03}, {"bm25_score": 12.0}, {"rank": 1}, {"rank": 9}, {},
        ):
            c = document_confidence(**kw)
            self.assertGreaterEqual(c, 0.30)
            self.assertLessEqual(c, 0.85)
        self.assertGreater(document_confidence(rerank_score=8.0),
                           document_confidence(rerank_score=-8.0))
        self.assertGreater(document_confidence(rank=1), document_confidence(rank=9))


class TestClaimConfidence(unittest.TestCase):
    def test_status_factor(self):
        s = [0.9, 0.8]
        self.assertGreater(claim_confidence(s, ClaimStatus.SUPPORTED),
                           claim_confidence(s, ClaimStatus.PARTIALLY_SUPPORTED))
        self.assertGreater(claim_confidence(s, ClaimStatus.PARTIALLY_SUPPORTED),
                           claim_confidence(s, ClaimStatus.NOT_SUPPORTED))
        self.assertEqual(claim_confidence([], ClaimStatus.SUPPORTED), 0.0)

    def test_graph_confidence_floored_by_not_supported(self):
        self.assertLessEqual(graph_confidence([0.9, 0.9], has_not_supported=True), 0.4)
        self.assertAlmostEqual(graph_confidence([0.8, 0.6]), 0.7)
        self.assertEqual(graph_confidence([]), 0.0)


if __name__ == "__main__":
    unittest.main()
