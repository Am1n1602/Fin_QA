"""Smoke test against the real finqa_v2.db, if it has been built. Skipped otherwise."""
from __future__ import annotations

import unittest

from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "finqa_v2.db not built")
class TestEngineReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        from database.v2.engine import FinancialEngine
        cls.eng = FinancialEngine(cls.repos)
        cls.has_tcs = cls.repos.companies.resolve("TCS") is not None

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_tcs_revenue_positive(self):
        if not self.has_tcs:
            self.skipTest("TCS not in db")
        r = self.eng.get_metric("TCS", "revenue")
        self.assertTrue(r.ok)
        self.assertGreater(r.value, 0)
        self.assertEqual(r.unit, "INR")

    def test_tcs_roe_reasonable(self):
        if not self.has_tcs:
            self.skipTest("TCS not in db")
        r = self.eng.get_ratio("TCS", "roe", period="latest_annual")
        if r.ok:
            self.assertGreater(r.value, 0)
            self.assertLess(r.value, 200)         # sanity band
            self.assertEqual(r.unit, "pct")

    def test_tcs_ebitda_margin(self):
        if not self.has_tcs:
            self.skipTest("TCS not in db")
        r = self.eng.get_ratio("TCS", "ebitda_margin", period="latest_annual")
        if r.ok:
            self.assertGreater(r.value, 0)
            self.assertLess(r.value, 100)

    def test_revenue_yoy_runs(self):
        if not self.has_tcs:
            self.skipTest("TCS not in db")
        r = self.eng.get_growth("TCS", "revenue", kind="yoy")
        self.assertEqual(r.kind, "growth")

    def test_compare_companies_shape(self):
        tickers = [c.ticker for c in self.repos.companies.list(active=True)][:5]
        out = self.eng.compare_companies("roe", tickers, period="latest_annual")
        self.assertIn("results", out)
        self.assertIn("missing", out)
        for row in out["results"]:
            self.assertIn("rank", row)

    def test_reliance_segments(self):
        if self.repos.companies.resolve("RELIANCE") is None:
            self.skipTest("RELIANCE not in db")
        r = self.eng.get_segment_data("RELIANCE", period="latest_annual")
        if not r.ok:
            self.skipTest("no segment data backfilled")
        self.assertGreaterEqual(len(r.rows), 3)
        self.assertAlmostEqual(sum(x.contribution_pct for x in r.rows), 100.0, places=4)
        g = self.eng.segment_growth("RELIANCE", kind="yoy")
        if g.ok:
            self.assertIsNotNone(g.total_change)

    def test_single_segment_company_returns_empty(self):
        # a company with no reportable segments -> ok=False + limitation, never a crash
        for t in ("HINDUNILVR", "NESTLEIND", "BRITANNIA", "ASIANPAINT"):
            if self.repos.companies.resolve(t) is None:
                continue
            r = self.eng.get_segment_data(t)
            self.assertIsInstance(r.rows, tuple)
            if not r.ok:
                self.assertTrue(r.limitations)
            break


if __name__ == "__main__":
    unittest.main()
