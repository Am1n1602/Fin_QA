"""build_period_records grouping / merging."""
from __future__ import annotations

import unittest
from datetime import date

from finqa_v2.engine.records import build_period_records
from finqa_v2.engine.tests._fixture import seed
from finqa_v2.sqlite import SqliteRepositories


class TestRecords(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.cid = seed(self.repos)

    def test_instant_merged_into_duration_for_same_period_end(self):
        recs = build_period_records(self.repos, self.cid, "consolidated")
        fy26 = next(r for r in recs if r.is_annual and r.financial_year == 2026)
        self.assertEqual(fy26.get("revenue"), 1200.0)          # from the duration fact
        self.assertEqual(fy26.get("total_assets"), 2400.0)     # merged from the BS snapshot
        self.assertEqual(fy26.get("total_equity"), 600.0)

    def test_quarters_are_single_quarter(self):
        recs = build_period_records(self.repos, self.cid, "consolidated")
        q1 = next(r for r in recs if r.quarter == 1)
        self.assertTrue(q1.is_single_quarter)
        self.assertFalse(q1.is_annual)
        self.assertEqual(q1.get("revenue"), 280.0)

    def test_sorted_chronologically(self):
        recs = build_period_records(self.repos, self.cid, "consolidated")
        ends = [r.period_end for r in recs]
        self.assertEqual(ends, sorted(ends))
        self.assertEqual(recs[-1].period_end, date(2026, 3, 31))

    def test_labels(self):
        recs = build_period_records(self.repos, self.cid, "consolidated")
        labels = {r.label for r in recs}
        self.assertIn("FY2026", labels)
        self.assertIn("FY2026 Q1", labels)

    def test_unknown_metric_absent(self):
        recs = build_period_records(self.repos, self.cid, "consolidated")
        self.assertNotIn("made_up", recs[-1].values)
        self.assertIsNone(recs[-1].get("made_up"))


if __name__ == "__main__":
    unittest.main()
