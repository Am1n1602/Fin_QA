"""normalize_canonical_record. python -m unittest database.v2.normalize.tests.test_pipeline"""
from __future__ import annotations

import unittest

from database.v2.models import Basis, StatementType
from database.v2.normalize.pipeline import normalize_canonical_record

_DURATION_REC = {
    "context_id": "OneD",
    "period_start": "2025-04-01",
    "period_end": "2025-06-30",
    "instant": None,
    "revenue": 219612000000.0,
    "total_income": 224366200000.0,
    "total_expenses": 209703400000.0,
    "pbt_before_exceptional": 14662800000.0,
    "exceptional_items": 0.0,
    "pbt": 14662800000.0,
    "net_profit": 9764800000.0,
    "eps_basic": 6.02,
    "_missing_fields": ["total_assets"],
}

_MERGED_REC = {
    "context_id": "OneD+OneI",
    "period_start": "2025-07-01",
    "period_end": "2025-09-30",
    "instant": None,
    "revenue": 100.0,
    "total_assets": 500.0,
    "total_liabilities": 300.0,
    "total_equity": 200.0,
}


class TestNormalizeRecord(unittest.TestCase):
    def test_basic_shape_and_units(self):
        facts = normalize_canonical_record(_DURATION_REC, company_id=1, basis="consolidated")
        by = {f.metric: f for f in facts}
        self.assertEqual(by["revenue"].unit, "INR")
        self.assertEqual(by["revenue"].currency, "INR")
        self.assertEqual(by["revenue"].value, 219612000000.0)
        self.assertEqual(by["eps_basic"].unit, "per_share")
        self.assertIsNone(by["eps_basic"].currency)
        for f in facts:
            self.assertIs(f.basis, Basis.CONSOLIDATED)
            self.assertEqual(f.financial_year, 2026)
            self.assertEqual(f.quarter, 1)
            self.assertIs(f.statement_type, StatementType.PROFIT_AND_LOSS)
            self.assertFalse(f.is_point_in_time)

    def test_meta_and_missing_keys_not_emitted(self):
        facts = normalize_canonical_record(_DURATION_REC, company_id=1, basis="consolidated")
        names = {f.metric for f in facts}
        self.assertNotIn("_missing_fields", names)
        self.assertNotIn("context_id", names)
        self.assertNotIn("total_assets", names)   # absent from the record -> not emitted
        self.assertEqual(names, {"revenue", "total_income", "total_expenses",
                                 "pbt_before_exceptional", "exceptional_items", "pbt",
                                 "net_profit", "eps_basic"})

    def test_zero_value_is_emitted(self):
        facts = normalize_canonical_record(_DURATION_REC, company_id=1, basis="consolidated")
        ex = next(f for f in facts if f.metric == "exceptional_items")
        self.assertEqual(ex.value, 0.0)
        self.assertFalse(ex.is_missing)

    def test_point_in_time_metrics_have_no_period_start_or_quarter(self):
        facts = normalize_canonical_record(_MERGED_REC, company_id=7, basis="standalone")
        by = {f.metric: f for f in facts}
        rev, ta = by["revenue"], by["total_assets"]
        # duration metric keeps the window + quarter
        self.assertEqual(rev.quarter, 2)
        self.assertIsNotNone(rev.period_start)
        self.assertIs(rev.statement_type, StatementType.PROFIT_AND_LOSS)
        # balance-sheet metric in the same merged record: snapshot only
        self.assertTrue(ta.is_point_in_time)
        self.assertIsNone(ta.period_start)
        self.assertIsNone(ta.quarter)
        self.assertIs(ta.statement_type, StatementType.BALANCE_SHEET)
        self.assertEqual(ta.financial_year, 2026)
        self.assertEqual(ta.problems(), [])

    def test_failed_validation_tags_mapping_reason(self):
        bad = dict(_DURATION_REC, pbt=999999.0)   # breaks pbt_before_exceptional + exceptional == pbt
        facts = normalize_canonical_record(bad, company_id=1, basis="consolidated")
        self.assertTrue(all(f.mapping_reason and "arithmetic checks" in f.mapping_reason for f in facts))

    def test_clean_record_has_no_mapping_reason(self):
        facts = normalize_canonical_record(_MERGED_REC, company_id=1, basis="consolidated")
        self.assertTrue(all(f.mapping_reason is None for f in facts))


if __name__ == "__main__":
    unittest.main()
