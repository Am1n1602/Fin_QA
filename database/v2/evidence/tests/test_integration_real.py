"""End-to-end assemble against the real finqa_v2.db: engine + retrieval -> workspace ->
claim graph -> §31 response. Skipped when the db / bm25 index is absent."""
from __future__ import annotations

import unittest
from pathlib import Path

from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_BM25 = Path(__file__).resolve().parents[4] / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "finqa_v2.db not built")
class TestAssemble(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_workspace_and_response(self):
        from database.v2.engine import FinancialEngine
        from database.v2.evidence import (
            ClaimGraph,
            evidence_from_engine_result,
            evidence_from_retrieved_chunk,
        )
        from database.v2.retrieval import BM25Index, HybridRetriever

        eng = FinancialEngine(self.repos)
        roe = eng.get_ratio("TCS", "roe", period="latest_annual")
        self.assertTrue(roe.ok)

        g = ClaimGraph()
        ev, calc = evidence_from_engine_result(roe, workspace=g.workspace)
        g.add_calculation(calc)
        self.assertGreaterEqual(len(g.workspace.by_type("financial_fact")), 1)

        bm25 = BM25Index.load(_BM25) if _BM25.exists() else BM25Index.build(self.repos)
        retr = HybridRetriever(self.repos, bm25=bm25)
        co = self.repos.companies.resolve("TCS")
        hits = retr.retrieve("return on equity net profit shareholders funds", k=3,
                             mode="lexical", filters={"company_id": co.company_id})
        for h in hits:
            evidence_from_retrieved_chunk(h, repos=self.repos, workspace=g.workspace)

        claim = g.add_claim(
            f"TCS ROE ({roe.period}) was {roe.value:.1f}%", kind="numeric",
            value=roe.value, unit="pct",
            evidence_ids=[ev.evidence_id], calculation_ids=[calc.calculation_id],
        )
        self.assertTrue(claim.is_supported)

        resp = g.to_response(f"TCS ROE was {roe.value:.1f}% in {roe.period}.")
        self.assertEqual(set(resp), {"answer", "confidence", "claims", "calculations",
                                     "evidence", "sources", "limitations"})
        self.assertGreater(resp["confidence"], 0.5)
        self.assertGreater(len(resp["evidence"]), 1)
        # document evidence carries a real citation with a page
        doc_ev = [e for e in resp["evidence"] if e["type"] == "document"]
        if doc_ev:
            self.assertIsNotNone(doc_ev[0]["citation"])
            self.assertIsNotNone(doc_ev[0]["citation"]["title"])


if __name__ == "__main__":
    unittest.main()
