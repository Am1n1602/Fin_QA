"""Source reconciliation audit: detects a fact-grain fed by conflicting filings."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from finqa_v2.dataset.reconcile import find_conflicts


class TestFindConflicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _write(self, name: str, records: list[dict]) -> None:
        (self.dir / name).write_text(json.dumps(records), encoding="utf-8")

    def test_no_conflict_when_grains_dont_overlap(self):
        self._write("TCS_consolidated_30-Jun-2023_canonical.json",
                    [{"period_start": "2023-04-01", "period_end": "2023-06-30", "revenue": 100.0}])
        self._write("TCS_consolidated_30-Sep-2023_canonical.json",
                    [{"period_start": "2023-07-01", "period_end": "2023-09-30", "revenue": 110.0}])
        self.assertEqual(find_conflicts(self.dir), [])

    def test_no_conflict_when_two_filings_agree(self):
        rec = {"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 2254580.0}
        self._write("TCS_consolidated_31-Mar-2023_canonical.json", [rec])
        self._write("TCS_consolidated_30-Jun-2023_canonical.json", [dict(rec)])  # same grain+value
        self.assertEqual(find_conflicts(self.dir), [])

    def test_flags_a_real_conflict(self):
        self._write("TCS_consolidated_31-Mar-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 2254580.0}])
        self._write("TCS_consolidated_30-Jun-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 2200000.0}])
        conflicts = find_conflicts(self.dir)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["metric"], "revenue")
        self.assertEqual(conflicts[0]["company"], "TCS")
        self.assertEqual(len(conflicts[0]["values_by_source"]), 2)

    def test_company_filter_scopes_the_search(self):
        self._write("TCS_consolidated_31-Mar-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 100.0}])
        self._write("TCS_consolidated_30-Jun-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 999.0}])
        self._write("INFY_consolidated_31-Mar-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31", "revenue": 500.0}])
        self.assertEqual(find_conflicts(self.dir, company="INFY"), [])
        self.assertEqual(len(find_conflicts(self.dir, company="TCS")), 1)

    def test_ignores_unrecognized_filenames_and_meta_keys(self):
        self._write("not_a_canonical_file.json", [{"revenue": 1.0}])
        self._write("TCS_consolidated_31-Mar-2023_canonical.json",
                    [{"period_start": "2022-04-01", "period_end": "2023-03-31",
                      "context_id": "FourD", "_needs_review": False, "revenue": 100.0}])
        self.assertEqual(find_conflicts(self.dir), [])


if __name__ == "__main__":
    unittest.main()
