"""Arithmetic validation. python -m unittest finqa_v2.normalize.tests.test_validate"""
from __future__ import annotations

import unittest

from finqa_v2.normalize.validate import validate_record


class TestValidateRecord(unittest.TestCase):
    def test_clean_pnl_passes(self):
        rec = {
            "total_income": 1000.0, "total_expenses": 800.0, "pbt_before_exceptional": 200.0,
            "exceptional_items": 0.0, "pbt": 200.0,
            "current_tax": 40.0, "deferred_tax": 10.0, "tax_expense": 50.0,
            "pat_continuing_ops": 150.0,
            "net_profit": 150.0, "oci": -5.0, "total_comprehensive_income": 145.0,
        }
        r = validate_record(rec)
        self.assertTrue(r.ran)
        self.assertFalse(r.needs_review)
        self.assertEqual(r.failed, [])

    def test_broken_income_identity_flags_review(self):
        rec = {"total_income": 1000.0, "total_expenses": 800.0, "pbt_before_exceptional": 999.0}
        r = validate_record(rec)
        self.assertTrue(r.needs_review)
        self.assertIn("income_minus_expenses_eq_pbt_before_exceptional", r.failed)

    def test_balance_sheet_identity(self):
        ok = validate_record({"total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 200.0})
        self.assertFalse(ok.needs_review)
        bad = validate_record({"total_assets": 500.0, "total_liabilities": 300.0, "total_equity": 100.0})
        self.assertTrue(bad.needs_review)

    def test_partial_record_runs_only_applicable_checks(self):
        r = validate_record({"revenue": 100.0})
        self.assertFalse(r.ran)          # nothing to check
        self.assertFalse(r.needs_review)

    def test_rounding_tolerance(self):
        r = validate_record({"total_assets": 500.0, "total_liabilities": 300.4, "total_equity": 199.7})
        self.assertFalse(r.needs_review)   # 0.1 diff within the abs_tol floor

    def test_large_scale_rounding_passes_with_relative_tolerance(self):
        # ~1.8e12 balance sheet, ~4e5 mismatch (2e-7) -> noise, not an error
        r = validate_record({
            "total_assets": 1_823_720_000_000.0,
            "total_liabilities": 1_100_000_000_000.0,
            "total_equity": 723_720_400_000.0,
        })
        self.assertFalse(r.needs_review)

    def test_large_scale_real_mismatch_still_flags(self):
        # same scale, ~5% mismatch -> a genuine problem
        r = validate_record({
            "total_assets": 1_823_720_000_000.0,
            "total_liabilities": 1_100_000_000_000.0,
            "total_equity": 630_000_000_000.0,
        })
        self.assertTrue(r.needs_review)
        self.assertIn("assets_eq_liabilities_plus_equity", r.failed)

    def test_tolerance_params_are_overridable(self):
        rec = {"total_assets": 1000.0, "total_liabilities": 600.0, "total_equity": 405.0}  # 5 off
        self.assertTrue(validate_record(rec).needs_review)                      # default: 5 > max(1, 0.5)
        self.assertFalse(validate_record(rec, rel_tol=0.01).needs_review)       # 5 <= 0.01*1000


if __name__ == "__main__":
    unittest.main()
