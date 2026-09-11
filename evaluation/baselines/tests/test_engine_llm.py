import unittest
from pathlib import Path

from evaluation.baselines.engine_llm import _fetch
from evaluation.baselines.tests._fakes import FakeProvider

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "database" / "data" / "finqa_v2.db"


class _FakeEngine:
    def __init__(self):
        self.calls: list[tuple] = []

    def get_ratio(self, ticker, name, period):
        self.calls.append(("ratio", ticker, name, period))
        return object()

    def get_valuation(self, ticker, name, period):
        self.calls.append(("valuation", ticker, name, period))
        return object()

    def get_metric(self, ticker, name, period):
        self.calls.append(("metric", ticker, name, period))
        return object()


class Fetch(unittest.TestCase):
    def test_routes_ratio(self):
        e = _FakeEngine()
        _fetch(e, "TCS", "roe", "FY2026")
        self.assertEqual(e.calls[0][0], "ratio")

    def test_routes_valuation(self):
        e = _FakeEngine()
        _fetch(e, "TCS", "pe", "FY2026")
        self.assertEqual(e.calls[0][0], "valuation")

    def test_routes_raw_metric(self):
        e = _FakeEngine()
        _fetch(e, "TCS", "revenue", "FY2026")
        self.assertEqual(e.calls[0][0], "metric")


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class EngineLlmReal(unittest.TestCase):
    def test_resolves_a_fact_and_prompts_the_llm(self):
        from finqa_v2.engine import FinancialEngine
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.baselines.engine_llm import answer

        repos = SqliteRepositories(DB)
        try:
            engine = FinancialEngine(repos)
            p = FakeProvider("TCS revenue in FY2026 was 2.67 lakh crore.")
            out = answer("What was TCS's revenue in FY2026?", repos, engine, p)
        finally:
            repos.close()
        self.assertTrue(out["llm_used"])
        self.assertIn("Figures:", p.calls[0]["prompt"])
        self.assertIn("TCS", p.calls[0]["prompt"])

    def test_no_company_found_short_circuits(self):
        from finqa_v2.engine import FinancialEngine
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.baselines.engine_llm import answer

        repos = SqliteRepositories(DB)
        try:
            engine = FinancialEngine(repos)
            p = FakeProvider()
            out = answer("What is the meaning of life?", repos, engine, p)
        finally:
            repos.close()
        self.assertFalse(out["llm_used"])
        self.assertEqual(p.usage["requests_made"], 0)


if __name__ == "__main__":
    unittest.main()
