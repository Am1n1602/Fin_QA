"""Full registry against the real finqa_v2.db + BM25 index (skipped if absent)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_BM25 = Path(__file__).resolve().parents[4] / "database" / "data" / "finqa_v2_bm25.pkl"


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "finqa_v2.db not built")
class TestRegistryReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")
        retriever = None
        if _BM25.exists():
            from database.v2.retrieval import BM25Index, HybridRetriever
            retriever = HybridRetriever(cls.repos, bm25=BM25Index.load(_BM25))
        from database.v2.tools import build_default_registry
        cls.reg = build_default_registry(cls.repos, retriever=retriever)
        cls.has_retriever = retriever is not None

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_financial_tools_on_real_data(self):
        r = self.reg.call("get_ratio", ticker="TCS", ratio="roe", period="latest_annual")
        self.assertTrue(r.ok, r.error)
        self.assertGreater(r.value["value"], 0)
        seg = self.reg.call("get_segment_data", ticker="RELIANCE", period="latest_annual")
        self.assertTrue(seg.ok)
        if seg.value["rows"]:
            self.assertAlmostEqual(sum(row["contribution_pct"] for row in seg.value["rows"]), 100.0, places=3)

    def test_company_tools(self):
        self.assertTrue(self.reg.call("get_company", ticker="TCS").ok)
        m = self.reg.call("get_index_members", index_name="NIFTY 50")
        self.assertTrue(m.ok)
        self.assertGreaterEqual(m.value["count"], 40)

    def test_search_documents(self):
        if not self.has_retriever:
            self.skipTest("no BM25 index")
        r = self.reg.call("search_documents", query="independent auditor report basis for opinion",
                          company="RELIANCE", k=3)
        self.assertTrue(r.ok, r.error)
        self.assertGreaterEqual(len(r.evidence), 1)
        self.assertEqual(r.evidence[0]["type"], "document")
        self.assertIsNotNone(r.evidence[0]["citation"])

    def test_get_document_section(self):
        r = self.reg.call("get_document_section", company="RELIANCE", section="segment_information", limit=3)
        self.assertTrue(r.ok, r.error)

    def test_trace_and_schemas(self):
        self.reg.reset_trace()
        self.reg.call("get_metric", ticker="TCS", metric="revenue")
        self.reg.call("get_metric", ticker="ZZZ", metric="revenue")
        s = self.reg.trace_summary()
        self.assertEqual(s["n_calls"], 2)
        self.assertEqual(s["errors"], 1)
        json.dumps(self.reg.schemas())


if __name__ == "__main__":
    unittest.main()
