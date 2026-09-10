"""The wired tools over an in-memory fixture (engine + repos, no retriever)."""
from __future__ import annotations

import json
import unittest

from database.v2.engine.tests._fixture import seed
from database.v2.models import Company, Index, IndexMembership
from database.v2.sqlite import SqliteRepositories
from database.v2.tools import build_default_registry
from database.v2.tools.registry import ALL_TOOLS


class ToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.cid = seed(self.repos)          # company TEST + FY2025/FY2026 facts + quarters
        # a tiny index + a peer for company tools
        peer = self.repos.companies.upsert(Company(name="Peerco", ticker="PEER", sector="IT"))
        self.repos.companies.upsert(Company(name="Testco", ticker="TEST", sector="IT"))
        idx = self.repos.indices.upsert(Index(name="NIFTY 50", provider="NSE"))
        for t in ("TEST", "PEER"):
            c = self.repos.companies.get_by_ticker(t)
            self.repos.indices.set_membership(IndexMembership(idx.index_id, c.company_id))
        self.repos.commit()
        self.reg = build_default_registry(self.repos)


class TestFinancialTools(ToolsTestCase):
    def test_all_tools_registered(self):
        self.assertEqual(set(self.reg.names()), set(ALL_TOOLS))

    def test_get_metric(self):
        r = self.reg.call("get_metric", ticker="TEST", metric="revenue", period="latest")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.value["value"], 1200.0)
        self.assertEqual(r.value["unit"], "INR")
        self.assertGreater(len(r.evidence), 0)
        self.assertGreaterEqual(r.latency_ms, 0.0)

    def test_get_ratio_with_evidence(self):
        r = self.reg.call("get_ratio", ticker="TEST", ratio="roe", period="latest")
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value["value"], 25.0)
        self.assertEqual(r.value["formula"], "net_profit / total_equity * 100")
        types = {e["type"] for e in r.evidence}
        self.assertIn("ratio", types)
        self.assertIn("financial_fact", types)

    def test_get_growth_and_cagr(self):
        g = self.reg.call("get_growth", ticker="TEST", metric="revenue", kind="yoy")
        self.assertTrue(g.ok)
        self.assertAlmostEqual(g.value["value"], 20.0)
        c = self.reg.call("get_cagr", ticker="TEST", metric="revenue")
        self.assertTrue(c.ok)
        self.assertAlmostEqual(c.value["value"], 20.0)

    def test_compare_periods_and_decompose(self):
        cp = self.reg.call("compare_periods", ticker="TEST", metrics=["revenue", "net_profit"],
                           a="FY2025", b="FY2026")
        self.assertTrue(cp.ok)
        self.assertEqual(cp.value["components"]["revenue"]["pct_change"], 20.0)
        d = self.reg.call("decompose_metric", ticker="TEST", metric="roe")
        self.assertTrue(d.ok)
        self.assertTrue(d.value["components"]["reconciles"])

    def test_compare_companies(self):
        r = self.reg.call("compare_companies", metric="roe", tickers=["TEST", "NOPE"])
        self.assertTrue(r.ok)
        self.assertEqual(r.value["results"][0]["ticker"], "TEST")
        self.assertTrue(any(m["ticker"] == "NOPE" for m in r.value["missing"]))

    def test_segment_data_empty_ok(self):
        r = self.reg.call("get_segment_data", ticker="TEST")
        self.assertTrue(r.ok)                       # empty, not an error
        self.assertEqual(r.value["rows"], [])
        self.assertTrue(r.value["limitations"])

    def test_unknown_company_is_ok_false(self):
        r = self.reg.call("get_metric", ticker="ZZZ", metric="revenue")
        self.assertFalse(r.ok)
        self.assertIn("unknown company", r.error)

    def test_bad_args_is_ok_false(self):
        r = self.reg.call("get_ratio", ticker="TEST")     # missing 'ratio'
        self.assertFalse(r.ok)
        self.assertIn("invalid input", r.error)


class TestCompanyMathDocTools(ToolsTestCase):
    def test_get_company(self):
        r = self.reg.call("get_company", ticker="TEST")
        self.assertTrue(r.ok)
        self.assertEqual(r.value["ticker"], "TEST")
        self.assertEqual(r.value["sector"], "IT")

    def test_get_peers(self):
        r = self.reg.call("get_peers", ticker="TEST")
        self.assertTrue(r.ok)
        self.assertEqual([p["ticker"] for p in r.value["peers"]], ["PEER"])

    def test_get_index_members(self):
        r = self.reg.call("get_index_members", index_name="NIFTY 50")
        self.assertTrue(r.ok)
        self.assertEqual(r.value["count"], 2)

    def test_calculate(self):
        r = self.reg.call("calculate", expression="(a - b) / b * 100", variables={"a": 120, "b": 100})
        self.assertTrue(r.ok)
        self.assertEqual(r.value["result"], 20.0)

    def test_calculate_rejects_unsafe(self):
        r = self.reg.call("calculate", expression="__import__('os').system('x')")
        self.assertFalse(r.ok)

    def test_search_documents_without_retriever(self):
        r = self.reg.call("search_documents", query="auditor opinion")
        self.assertFalse(r.ok)
        self.assertIn("retriever", r.error)

    def test_schemas_serializable_and_complete(self):
        schemas = self.reg.schemas()
        json.dumps(schemas)
        self.assertEqual({s["name"] for s in schemas}, set(ALL_TOOLS))
        for s in schemas:
            self.assertIn("parameters", s)
            self.assertEqual(s["parameters"]["type"], "object")


if __name__ == "__main__":
    unittest.main()
