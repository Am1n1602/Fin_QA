"""ReasoningOrchestrator end-to-end with NullProvider (no tokens spent)."""
from __future__ import annotations

import unittest

from finqa_v2.engine.tests._fixture import seed as seed_engine
from finqa_v2.models import Company, Index, IndexMembership
from finqa_v2.reasoning import ReasoningOrchestrator
from finqa_v2.sqlite import SqliteRepositories

_KEYS = {"answer", "confidence", "claims", "calculations", "evidence", "sources", "limitations"}


class OrchestratorTestCase(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed_engine(self.repos)                       # company TEST + FY2025/FY2026 facts + quarters
        for name, tkr in [("Peerco", "PEER"), ("Otherco", "OTHR")]:
            self.repos.companies.upsert(Company(name=name, ticker=tkr, sector="IT"))
        self.repos.companies.upsert(Company(name="Testco", ticker="TEST", sector="IT"))
        idx = self.repos.indices.upsert(Index(name="NIFTY 50", provider="NSE"))
        for tkr in ("TEST", "PEER", "OTHR"):
            c = self.repos.companies.get_by_ticker(tkr)
            self.repos.indices.set_membership(IndexMembership(idx.index_id, c.company_id))
        self.repos.commit()
        self.orch = ReasoningOrchestrator(self.repos)   # NullProvider by default


class TestOrchestrator(OrchestratorTestCase):
    def test_numeric_fact(self):
        r = self.orch.answer("What was TEST revenue in FY2026?")
        self.assertEqual(set(r.response), _KEYS)
        self.assertFalse(r.llm_used)
        self.assertIn("get_metric", r.tools_run)
        self.assertIn("1,200", r.answer)
        self.assertTrue(r.response["evidence"])
        self.assertTrue(r.trace)
        self.assertGreater(r.latency_ms, 0)

    def test_ratio_has_calculation(self):
        r = self.orch.answer("What was TEST ROE in FY2026?")
        self.assertIn("get_ratio", r.tools_run)
        self.assertTrue(r.response["calculations"])
        self.assertAlmostEqual(r.response["calculations"][0]["result"], 25.0)
        self.assertIn("25.00 pct", r.answer)

    def test_trend(self):
        r = self.orch.answer("How has TEST revenue changed over the years?")
        self.assertIn("get_growth", r.tools_run)
        self.assertTrue(any(e["type"] == "growth" for e in r.response["evidence"]))

    def test_comparison_resolves_universe(self):
        r = self.orch.answer("Compare companies on ROE.")     # no companies named
        self.assertIn("compare_companies", r.tools_run)
        # get_index_members was used to resolve the universe
        self.assertIn("get_index_members", [c["tool"] for c in r.trace])
        cc = next(c for c in r.trace if c["tool"] == "compare_companies")
        self.assertTrue(cc["ok"])

    def test_causal_without_docs_flags_limitation(self):
        r = self.orch.answer("Why did TEST net profit rise in FY2026?")
        self.assertIn("get_growth", r.tools_run)
        self.assertTrue(any("not established" in l for l in r.response["limitations"]))

    def test_unknown_question_degrades_gracefully(self):
        r = self.orch.answer("what is the meaning of life")
        self.assertEqual(set(r.response), _KEYS)
        self.assertEqual(r.tools_run, [])
        self.assertIn("not sufficient", r.answer)

    def test_to_dict_roundtrip(self):
        import json
        r = self.orch.answer("What was TEST revenue in FY2026?")
        json.dumps(r.to_dict())

    def test_max_tools_bound(self):
        orch = ReasoningOrchestrator(self.repos, max_tools=1)
        r = orch.answer("Give me a fundamental overview of TEST.")   # rules plan wants 4 tools
        self.assertLessEqual(len(r.tools_run), 1)


if __name__ == "__main__":
    unittest.main()
