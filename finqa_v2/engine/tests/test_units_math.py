"""derive / ratios / growth / calculator pure-math tests."""
from __future__ import annotations

import unittest

from finqa_v2.engine import derive, growth, ratios
from finqa_v2.engine.calculator import calculate


class TestDerive(unittest.TestCase):
    R = {"pbt_before_exceptional": 210.0, "finance_costs": 12.0, "depreciation": 48.0,
         "other_income": 0.0, "revenue": 1200.0, "employee_expense": 600.0,
         "other_expenses": 342.0, "borrowings_noncurrent": 240.0, "cash_and_equivalents": 180.0,
         "capex_ppe": 30.0, "capex_intangibles": 5.0}

    def test_ebit(self):
        self.assertEqual(derive.ebit(self.R), 222.0)
        self.assertIsNone(derive.ebit({"finance_costs": 1.0}))

    def test_ebitda(self):
        self.assertEqual(derive.ebitda(self.R), 210.0 + 48.0 + 12.0 - 0.0)

    def test_operating_ebit(self):
        self.assertEqual(derive.operating_ebit(self.R), 1200.0 - 600.0 - 48.0 - 342.0)

    def test_total_and_net_debt(self):
        self.assertEqual(derive.total_debt(self.R), 240.0)
        self.assertEqual(derive.net_debt(self.R), 60.0)
        self.assertIsNone(derive.net_debt({"borrowings_noncurrent": 100.0}))  # cash missing

    def test_capex(self):
        self.assertEqual(derive.capex(self.R), 35.0)
        self.assertIsNone(derive.capex({}))

    def test_shares_outstanding(self):
        self.assertEqual(derive.shares_outstanding({"paid_up_equity_capital": 100.0, "face_value_per_share": 2.0}), 50.0)
        self.assertIsNone(derive.shares_outstanding({"paid_up_equity_capital": 100.0, "face_value_per_share": 0}))


class TestRatios(unittest.TestCase):
    FY26 = {"revenue": 1200.0, "net_profit": 150.0, "total_equity": 600.0, "total_assets": 2400.0,
            "current_liabilities": 360.0, "current_assets": 720.0, "pbt": 210.0,
            "pbt_before_exceptional": 210.0, "finance_costs": 12.0, "depreciation": 48.0,
            "other_income": 0.0, "tax_expense": 60.0, "borrowings_noncurrent": 240.0,
            "cash_and_equivalents": 180.0}

    def _r(self, name):
        return ratios.get_spec(name).compute(self.FY26)

    def test_headline_ratios(self):
        self.assertAlmostEqual(self._r("roe"), 25.0)
        self.assertAlmostEqual(self._r("roa"), 6.25)
        self.assertAlmostEqual(self._r("roce"), 222.0 / 2040.0 * 100)
        self.assertAlmostEqual(self._r("ebitda_margin"), 22.5)
        self.assertAlmostEqual(self._r("ebit_margin"), 18.5)
        self.assertAlmostEqual(self._r("net_profit_margin"), 12.5)
        self.assertAlmostEqual(self._r("debt_to_equity"), 0.4)
        self.assertAlmostEqual(self._r("interest_coverage"), 17.5)
        self.assertAlmostEqual(self._r("current_ratio"), 2.0)
        self.assertAlmostEqual(self._r("asset_turnover"), 0.5)
        self.assertAlmostEqual(self._r("effective_tax_rate"), 60.0 / 210.0 * 100)

    def test_missing_input_is_none_not_zero(self):
        self.assertIsNone(ratios.get_spec("roe").compute({"net_profit": 100.0}))          # no equity
        self.assertIsNone(ratios.get_spec("roe").compute({"net_profit": 100.0, "total_equity": 0}))

    def test_alias_resolution(self):
        self.assertEqual(ratios.resolve("Return_On_Equity"), "roe")
        self.assertEqual(ratios.resolve("D/E"), "debt_to_equity")
        self.assertEqual(ratios.resolve("nim"), "net_interest_margin")
        self.assertIsNone(ratios.resolve("made_up_ratio"))


class TestGrowth(unittest.TestCase):
    def test_pct_and_abs(self):
        self.assertEqual(growth.pct_change(1000, 1200), 20.0)
        self.assertEqual(growth.abs_change(1000, 1200), 200)
        self.assertIsNone(growth.pct_change(None, 5))

    def test_negative_base_pct_is_none(self):
        self.assertIsNone(growth.pct_change(-50, 20))
        self.assertIsNone(growth.pct_change(0, 20))
        self.assertEqual(growth.abs_change(-50, 20), 70)

    def test_cagr(self):
        self.assertAlmostEqual(growth.cagr(100, 200, 1), 100.0)
        self.assertAlmostEqual(growth.cagr(100, 400, 2), 100.0)   # 100 -> 200 -> 400
        self.assertIsNone(growth.cagr(0, 400, 2))
        self.assertIsNone(growth.cagr(100, 400, 0))


class TestCalculator(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(calculate("2 + 3 * 4"), 14.0)
        self.assertEqual(calculate("(a - b) / b * 100", a=120, b=100), 20.0)
        self.assertEqual(calculate("max(1, 2, 3) + abs(-4)"), 7.0)
        self.assertEqual(calculate("2 ** 10"), 1024.0)

    def test_rejects_unsafe(self):
        for bad in ("__import__('os')", "a.b", "open('x')", "[i for i in range(3)]",
                    "lambda: 1", "unknown_var + 1"):
            with self.assertRaises(ValueError, msg=bad):
                calculate(bad, a=1)

    def test_none_variable_raises(self):
        with self.assertRaises(ValueError):
            calculate("x + 1", x=None)


if __name__ == "__main__":
    unittest.main()
