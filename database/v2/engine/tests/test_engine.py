"""FinancialEngine facade end-to-end on the in-memory fixture."""
from __future__ import annotations

import unittest

from database.v2.engine import FinancialEngine
from database.v2.engine.engine import EngineError
from database.v2.engine.tests._fixture import seed
from database.v2.sqlite import SqliteRepositories


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.eng = FinancialEngine(self.repos)

    # --- get_metric ---
    def test_get_metric_raw_latest(self):
        r = self.eng.get_metric("TEST", "revenue")
        self.assertTrue(r.ok)
        self.assertEqual(r.value, 1200.0)
        self.assertEqual(r.unit, "INR")
        self.assertEqual(r.period, "FY2026")
        self.assertEqual(r.inputs[0].metric, "revenue")

    def test_get_metric_derived(self):
        self.assertEqual(self.eng.get_metric("TEST", "ebitda").value, 270.0)
        self.assertEqual(self.eng.get_metric("TEST", "total_debt").value, 240.0)
        self.assertEqual(self.eng.get_metric("TEST", "net_debt").value, 60.0)

    def test_get_metric_specific_period(self):
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period="FY2025").value, 1000.0)
        self.assertEqual(self.eng.get_metric("TEST", "revenue", period="FY2026Q1").value, 280.0)

    def test_get_metric_missing_is_none_with_limitation(self):
        r = self.eng.get_metric("TEST", "shares_outstanding")
        self.assertIsNone(r.value)
        self.assertTrue(r.limitations)

    # --- get_ratio ---
    def test_get_ratio(self):
        self.assertAlmostEqual(self.eng.get_ratio("TEST", "roe").value, 25.0)
        self.assertAlmostEqual(self.eng.get_ratio("TEST", "ebitda_margin").value, 22.5)
        self.assertAlmostEqual(self.eng.get_ratio("TEST", "leverage").value, 0.4)   # alias -> debt_to_equity
        r = self.eng.get_ratio("TEST", "roe")
        self.assertEqual(r.unit, "pct")
        self.assertIn("net_profit", [i.metric for i in r.inputs])

    def test_unknown_ratio(self):
        r = self.eng.get_ratio("TEST", "sharpe_ratio")
        self.assertIsNone(r.value)
        self.assertIn("unknown ratio", r.limitations[0])

    # --- growth / cagr ---
    def test_growth_yoy(self):
        r = self.eng.get_growth("TEST", "revenue", kind="yoy")
        self.assertAlmostEqual(r.value, 20.0)
        self.assertEqual(r.components["abs_change"], 200.0)

    def test_growth_qoq(self):
        r = self.eng.get_growth("TEST", "revenue", kind="qoq")
        self.assertAlmostEqual(r.value, 280.0 / 280 * 0 + (300 - 280) / 280 * 100)

    def test_cagr(self):
        r = self.eng.get_cagr("TEST", "revenue")
        self.assertAlmostEqual(r.value, 20.0)
        self.assertEqual(r.components["years"], 1)

    # --- compare ---
    def test_compare_periods(self):
        r = self.eng.compare_periods("TEST", ["revenue", "net_profit"], a="FY2025", b="FY2026")
        self.assertEqual(r.components["revenue"]["pct_change"], 20.0)
        self.assertEqual(r.components["net_profit"]["abs_change"], 50.0)

    def test_compare_companies(self):
        # only one company in the fixture; still exercises the shape
        out = self.eng.compare_companies("roe", ["TEST", "NOPE"])
        self.assertEqual(out["results"][0]["ticker"], "TEST")
        self.assertEqual(out["results"][0]["rank"], 1)
        self.assertTrue(any(m["ticker"] == "NOPE" for m in out["missing"]))

    # --- decompose ---
    def test_decompose_roe(self):
        r = self.eng.decompose_metric("TEST", "roe")
        self.assertAlmostEqual(r.value, 25.0)
        c = r.components
        self.assertAlmostEqual(c["components"]["net_profit_margin"], 12.5)
        self.assertAlmostEqual(c["components"]["asset_turnover"], 0.5)
        self.assertAlmostEqual(c["components"]["equity_multiplier"], 4.0)
        self.assertTrue(c["reconciles"])

    def test_decompose_net_margin_bridge(self):
        r = self.eng.decompose_metric("TEST", "net_margin")
        self.assertTrue(r.components["available"])
        self.assertAlmostEqual(r.components["net_margin_prev_pct"], 10.0)     # 100/1000
        self.assertAlmostEqual(r.components["net_margin_curr_pct"], 12.5)     # 150/1200
        self.assertAlmostEqual(
            r.components["revenue_effect_pp"] + r.components["expense_effect_pp"],
            r.components["net_margin_change_pp"],
        )

    # --- calculate ---
    def test_calculate(self):
        r = self.eng.calculate("(a - b) / b * 100", a=1200, b=1000)
        self.assertEqual(r.value, 20.0)
        self.assertFalse(self.eng.calculate("a +").ok)

    # --- guards ---
    def test_segment_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            self.eng.get_segment_data("TEST")

    def test_unknown_company_raises(self):
        with self.assertRaises(EngineError):
            self.eng.get_metric("DOESNOTEXIST", "revenue")

    def test_no_llm_imports(self):
        import database.v2.engine.engine as mod
        src = __import__("inspect").getsource(mod)
        for banned in ("import openai", "anthropic", "llm_router", "ollama", "groq"):
            self.assertNotIn(banned, src.lower())


if __name__ == "__main__":
    unittest.main()
