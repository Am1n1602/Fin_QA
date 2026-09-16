"""HypothesisTester against the real finqa_v2.db (+ BM25). The no-LLM path runs
whenever the db exists; the LLM path is gated behind FINQA_LLM_TESTS=1.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from finqa_v2.evidence import ClaimStatus, EvidenceSet
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_BM25 = Path(__file__).resolve().parents[3] / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "needs database/data/finqa_v2.db")
class TestTesterReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.engine import FinancialEngine

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")
        cls.engine = FinancialEngine(cls.repos)
        cls.retriever = None
        if _BM25.exists():
            try:
                from finqa_v2.retrieval import BM25Index, HybridRetriever

                cls.retriever = HybridRetriever(cls.repos, bm25=BM25Index.load(_BM25))
            except Exception as e:                       # rank_bm25 / torch not installed here
                print(f"(retriever unavailable: {e}) -- running structural-only")

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_deterministic_run(self):
        from finqa_v2.hypothesis import HypothesisTester

        tester = HypothesisTester(self.repos, engine=self.engine, retriever=self.retriever)
        ws = EvidenceSet()
        rep = tester.run("Why did TCS net profit change in FY2026?", "TCS", "net_profit",
                         workspace=ws, use_llm=False)
        self.assertIsNotNone(rep.change)
        self.assertTrue(rep.hypotheses)
        for h in rep.hypotheses:
            self.assertIn(h.status, set(ClaimStatus))
            for eid in h.support_evidence_ids:
                self.assertIsNotNone(ws.get(eid))
        json.dumps(rep.to_dict())
        if self.retriever is not None:
            print("\nTCS net-profit hypotheses:")
            for h in rep.ranked:
                print(f"  [{h.status.value}] {h.statement} — {h.structural_note} "
                      f"(docs: {len(h.doc_evidence_ids)})")

    @unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1",
                         "set FINQA_LLM_TESTS=1 to run (spends Groq tokens)")
    def test_llm_run(self):
        from finqa_v2.hypothesis import HypothesisTester
        from finqa_v2.llm import RateBudget, provider_from_env

        budget = RateBudget.from_env()
        tester = HypothesisTester(self.repos, engine=self.engine, retriever=self.retriever,
                                  provider=provider_from_env(budget=budget))
        rep = tester.run("Why did TCS operating margin change in FY2026?", "TCS", "ebit_margin",
                         use_llm=True)
        self.assertIsNotNone(rep.change)
        self.assertTrue(any(h.origin == "llm" for h in rep.hypotheses) or rep.hypotheses)
        json.dumps(rep.to_dict())
        print("\nLLM usage:", budget.usage)


if __name__ == "__main__":
    unittest.main()
