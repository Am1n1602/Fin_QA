"""HypothesisTester end to end on the in-memory engine fixture (no LLM, no retriever)."""
from __future__ import annotations

import json
import unittest

from finqa_v2.evidence import ClaimStatus, EvidenceSet
from finqa_v2.hypothesis import HypothesisTester
from finqa_v2.hypothesis.tests._fixture import engine_repos

_STATUSES = {s for s in ClaimStatus}


class TestTester(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.repos = engine_repos()

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def setUp(self):
        self.tester = HypothesisTester(self.repos, engine=self.engine)   # NullProvider, no retriever

    def test_quantifies_and_generates(self):
        rep = self.tester.run("Why did TEST net profit rise in FY2026?", "TEST", "net_profit")
        self.assertIsNotNone(rep.change)
        self.assertEqual(rep.change.direction, "increase")
        self.assertTrue(rep.hypotheses)
        for h in rep.hypotheses:
            self.assertIn(h.status, _STATUSES)
            self.assertTrue(h.support_evidence_ids)      # each claim is pinned to some evidence
        self.assertEqual(len(rep.steps), 4)

    def test_no_docs_means_partial_not_supported(self):
        rep = self.tester.run("Why did TEST net profit rise?", "TEST", "net_profit")
        # structural checks agree, but nothing is SUPPORTED without commentary
        self.assertFalse(rep.has_confirmed_cause)
        self.assertTrue(any(h.status is ClaimStatus.PARTIALLY_SUPPORTED for h in rep.hypotheses))
        self.assertTrue(any("retriever" in l for l in rep.limitations))

    def test_workspace_is_shared_and_populated(self):
        ws = EvidenceSet()
        rep = self.tester.run("Why did TEST net profit rise?", "TEST", "net_profit", workspace=ws)
        self.assertGreater(len(ws), 2)
        ids = {e.evidence_id for e in ws}
        for h in rep.hypotheses:
            for eid in h.support_evidence_ids:
                self.assertIn(eid, ids)

    def test_report_is_json_serialisable(self):
        rep = self.tester.run("Why did TEST net profit rise?", "TEST", "net_profit")
        d = rep.to_dict()
        json.dumps(d)
        self.assertEqual(d["change"]["direction"], "increase")
        self.assertTrue(d["decomposition"])

    def test_other_metric_target_degrades_cleanly(self):
        rep = self.tester.run("Why did TEST cash change?", "TEST", "cash_and_equivalents")
        self.assertIsNotNone(rep.change)
        self.assertIn(rep.change.direction, {"increase", "decrease", "flat"})
        json.dumps(rep.to_dict())

    def test_ranked_orders_supported_first(self):
        rep = self.tester.run("Why did TEST net profit rise?", "TEST", "net_profit")
        order = [h.status for h in rep.ranked]
        # partially_supported (all of them here) should precede any insufficient/not_supported
        seen_weak = False
        for s in order:
            if s in (ClaimStatus.INSUFFICIENT_EVIDENCE, ClaimStatus.NOT_SUPPORTED):
                seen_weak = True
            elif seen_weak:
                self.fail("a strong hypothesis appeared after a weak one in ranked order")


if __name__ == "__main__":
    unittest.main()
