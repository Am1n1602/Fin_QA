"""Real end-to-end reasoning against finqa_v2.db + Groq. Gated behind FINQA_LLM_TESTS=1."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_BM25 = Path(__file__).resolve().parents[3] / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1" and DEFAULT_V2_DB_PATH.exists(),
                     "set FINQA_LLM_TESTS=1 to run (spends Groq tokens)")
class TestReasoningReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.llm import RateBudget, provider_from_env
        from finqa_v2.reasoning import ReasoningOrchestrator
        from finqa_v2.retrieval import BM25Index, HybridRetriever

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")
        retriever = HybridRetriever(cls.repos, bm25=BM25Index.load(_BM25)) if _BM25.exists() else None
        cls.budget = RateBudget.from_env()
        cls.orch = ReasoningOrchestrator(cls.repos, provider=provider_from_env(budget=cls.budget),
                                         retriever=retriever)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()
        print("\nLLM usage:", cls.budget.usage)

    def _check_grounded(self, r):
        ev_ids = {e["evidence_id"] for e in r.response["evidence"]}
        for c in r.response["claims"]:
            for cid in c["evidence_ids"]:
                self.assertIn(cid, ev_ids, "claim cites an evidence_id not in the workspace")
        self.assertTrue(r.answer.strip())
        self.assertGreaterEqual(r.confidence, 0.0)
        self.assertLessEqual(r.confidence, 1.0)

    def test_numeric(self):
        r = self.orch.answer("What was TCS ROE in FY2026?")
        self.assertTrue(r.llm_used)
        self.assertIn("get_ratio", r.tools_run)
        self._check_grounded(r)

    def test_causal(self):
        r = self.orch.answer("Why did TCS operating margin change in FY2026?")
        self.assertIn("search_documents", r.tools_run)
        self._check_grounded(r)

    def test_segment(self):
        r = self.orch.answer("Which segment contributed most to Reliance's revenue growth?")
        self.assertIn("get_segment_data", r.tools_run)
        self._check_grounded(r)


if __name__ == "__main__":
    unittest.main()
