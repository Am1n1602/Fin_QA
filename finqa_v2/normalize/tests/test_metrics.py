"""Metric registry. python -m unittest finqa_v2.normalize.tests.test_metrics"""
from __future__ import annotations

import unittest

from finqa_v2.models import StatementType
from finqa_v2.normalize import metrics
from finqa_v2.normalize.units import currency_for, unit_for


class TestRegistry(unittest.TestCase):
    def test_revenue(self):
        s = metrics.get("revenue")
        self.assertEqual(s.unit, "INR")
        self.assertIs(s.statement_type, StatementType.PROFIT_AND_LOSS)
        self.assertFalse(s.is_point_in_time)

    def test_eps_is_per_share(self):
        self.assertEqual(metrics.get("eps_basic").unit, "per_share")
        self.assertEqual(metrics.get("eps_diluted").unit, "per_share")
        self.assertIsNone(currency_for("eps_basic"))

    def test_balance_sheet_is_point_in_time(self):
        for name in ("total_assets", "total_equity", "cash_and_equivalents", "advances"):
            s = metrics.get(name)
            self.assertTrue(s.is_point_in_time, msg=name)
            self.assertIs(s.statement_type, StatementType.BALANCE_SHEET, msg=name)

    def test_capital_fields_are_balance_sheet_but_not_point_in_time(self):
        # Reported under duration (OneD/FourD) contexts, never instant -- collapsing
        # period_start would silently merge a quarter figure with a same-period_end
        # cumulative figure that can legitimately differ (see metrics.py comment).
        for name in ("paid_up_equity_capital", "face_value_per_share"):
            s = metrics.get(name)
            self.assertFalse(s.is_point_in_time, msg=name)
            self.assertIs(s.statement_type, StatementType.BALANCE_SHEET, msg=name)

    def test_cash_flow_bucket(self):
        for name in ("operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
                     "dividends", "capex_ppe", "capex_intangibles"):
            self.assertIs(metrics.get(name).statement_type, StatementType.CASH_FLOW, msg=name)
            self.assertFalse(metrics.get(name).is_point_in_time, msg=name)

    def test_reported_ratio(self):
        for name in ("debt_equity_ratio_reported", "debt_service_coverage_ratio_reported",
                     "interest_service_coverage_ratio_reported"):
            s = metrics.get(name)
            self.assertEqual(s.unit, "x", msg=name)
            self.assertIs(s.statement_type, StatementType.OTHER, msg=name)
            self.assertIsNone(currency_for(name), msg=name)

    def test_currency_for_inr_metric(self):
        self.assertEqual(currency_for("revenue"), "INR")
        self.assertEqual(unit_for("revenue"), "INR")

    def test_unknown_metric(self):
        self.assertIsNone(metrics.get("ScripCode"))
        self.assertFalse(metrics.is_known("Symbol"))
        self.assertIsNone(unit_for("nonsense"))

    def test_bank_metrics_present(self):
        for name in ("bank_interest_earned", "bank_provisions", "advances"):
            self.assertTrue(metrics.is_known(name), msg=name)

    def test_bank_capital_ratios_are_reported_ratios(self):
        for name in ("cet1_ratio", "additional_tier1_ratio", "gross_npa_ratio",
                     "net_npa_ratio", "return_on_assets"):
            s = metrics.get(name)
            self.assertEqual(s.unit, "x", msg=name)
            self.assertIs(s.statement_type, StatementType.OTHER, msg=name)
            self.assertFalse(s.is_point_in_time, msg=name)

    def test_npa_absolute_values_are_balance_sheet_but_not_point_in_time(self):
        for name in ("gross_npa", "net_npa"):
            s = metrics.get(name)
            self.assertEqual(s.unit, "INR", msg=name)
            self.assertIs(s.statement_type, StatementType.BALANCE_SHEET, msg=name)
            self.assertFalse(s.is_point_in_time, msg=name)


if __name__ == "__main__":
    unittest.main()
