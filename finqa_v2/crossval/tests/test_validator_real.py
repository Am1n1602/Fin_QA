"""CrossValidator against the real finqa_v2.db (+ BM25 when available). Structural path
runs whenever the db exists; the LLM path is gated behind FINQA_LLM_TESTS=1.
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
class TestCrossValidatorReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.engine import FinancialEngine

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("HCLTECH") is None:
            raise unittest.SkipTest("HCLTECH not in db")
        cls.engine = FinancialEngine(cls.repos)
        cls.retriever = None
        if _BM25.exists():
            try:
                from finqa_v2.retrieval import BM25Index, HybridRetriever

                cls.retriever = HybridRetriever(cls.repos, bm25=BM25Index.load(_BM25))
            except Exception as e:
                print(f"(retriever unavailable: {e}) -- structural-only")

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_margin_expansion_claim_is_rejected(self):
        from finqa_v2.crossval import CrossValidator

        cv = CrossValidator(self.repos, engine=self.engine, retriever=self.retriever)
        ws = EvidenceSet()
        r = cv.validate("HCLTECH management highlighted margin expansion. Is this visible in "
                        "the financial statements?", "HCLTECH", workspace=ws, use_llm=False)
        self.assertIsNotNone(r.claim)
        # HCLTECH net margin fell FY25->FY26 -> the claim must not come back SUPPORTED
        self.assertIn(r.status, {ClaimStatus.NOT_SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED})
        self.assertTrue(any(c.verdict == "contradicts" for c in r.checks))
        for eid in r.support_evidence_ids:
            self.assertIsNotNone(ws.get(eid))
        json.dumps(r.to_dict())

    def test_segment_attribution_acronym(self):
        from finqa_v2.crossval import CrossValidator

        cv = CrossValidator(self.repos, engine=self.engine, retriever=self.retriever)
        r = cv.validate("TCS management attributed revenue growth to the BFSI segment. "
                        "Is that supported by segment data?", "TCS", use_llm=False)
        seg = [c for c in r.checks if c.name == "segment_attribution"]
        self.assertTrue(seg)
        self.assertIn(seg[0].verdict, {"agrees", "unrelated", "contradicts"})  # matched a segment
        print(f"\nTCS/BFSI: [{r.status.value}] {seg[0].detail}")

    @unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1",
                         "set FINQA_LLM_TESTS=1 to run (spends Groq tokens)")
    def test_llm_mechanism_fill(self):
        from finqa_v2.crossval import CrossValidator
        from finqa_v2.llm import RateBudget, provider_from_env

        budget = RateBudget.from_env()
        cv = CrossValidator(self.repos, engine=self.engine, retriever=self.retriever,
                            provider=provider_from_env(budget=budget))
        r = cv.validate("Management said the improvement came from better execution and "
                        "premiumisation. Is that consistent with TCS's reported financials?",
                        "TCS", use_llm=True)
        self.assertIsNotNone(r.claim)
        json.dumps(r.to_dict())
        print("\nLLM usage:", budget.usage)


if __name__ == "__main__":
    unittest.main()
