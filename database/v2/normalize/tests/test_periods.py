"""Period normalization edge cases. python -m unittest database.v2.normalize.tests.test_periods"""
from __future__ import annotations

import unittest
from datetime import date

from database.v2.normalize.periods import fiscal_year, normalize_period


class TestFiscalYear(unittest.TestCase):
    def test_mapping(self):
        self.assertEqual(fiscal_year(date(2026, 3, 31)), 2026)
        self.assertEqual(fiscal_year(date(2026, 4, 1)), 2027)
        self.assertEqual(fiscal_year(date(2025, 6, 30)), 2026)
        self.assertEqual(fiscal_year(date(2026, 1, 1)), 2026)


class TestNormalizePeriod(unittest.TestCase):
    def test_full_year(self):
        p = normalize_period("2025-04-01", "2026-03-31", None)
        self.assertEqual(p.financial_year, 2026)
        self.assertTrue(p.is_annual)
        self.assertIsNone(p.quarter)
        self.assertFalse(p.is_point_in_time)
        self.assertEqual(p.period_end, date(2026, 3, 31))

    def test_each_quarter(self):
        cases = [
            ("2025-04-01", "2025-06-30", 1),
            ("2025-07-01", "2025-09-30", 2),
            ("2025-10-01", "2025-12-31", 3),
            ("2026-01-01", "2026-03-31", 4),
        ]
        for ps, pe, q in cases:
            p = normalize_period(ps, pe, None)
            self.assertEqual(p.quarter, q, msg=f"{ps}..{pe}")
            self.assertEqual(p.financial_year, 2026, msg=f"{ps}..{pe}")
            self.assertFalse(p.is_annual)

    def test_instant_only_is_point_in_time(self):
        p = normalize_period(None, None, "2026-03-31")
        self.assertTrue(p.is_point_in_time)
        self.assertIsNone(p.period_start)
        self.assertIsNone(p.quarter)
        self.assertFalse(p.is_annual)
        self.assertEqual(p.financial_year, 2026)
        self.assertEqual(p.period_end, date(2026, 3, 31))

    def test_ytd_half_year_has_no_quarter(self):
        p = normalize_period("2025-04-01", "2025-09-30", None)
        self.assertIsNone(p.quarter)
        self.assertFalse(p.is_annual)
        self.assertEqual(p.financial_year, 2026)

    def test_nine_month_ytd_has_no_quarter(self):
        p = normalize_period("2025-04-01", "2025-12-31", None)
        self.assertIsNone(p.quarter)
        self.assertFalse(p.is_annual)

    def test_all_none(self):
        p = normalize_period(None, None, None)
        self.assertIsNone(p.financial_year)
        self.assertIsNone(p.period_end)
        self.assertFalse(p.is_point_in_time)
        self.assertFalse(p.is_annual)

    def test_accepts_date_objects(self):
        p = normalize_period(date(2025, 4, 1), date(2025, 6, 30), None)
        self.assertEqual(p.quarter, 1)


if __name__ == "__main__":
    unittest.main()
