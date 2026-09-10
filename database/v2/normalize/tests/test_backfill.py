"""Backfill against fixtures. python -m unittest database.v2.normalize.tests.test_backfill"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from database.v2.models import Company
from database.v2.normalize.backfill import run_backfill
from database.v2.sqlite import SqliteRepositories

_REC_Q1 = {
    "context_id": "OneD", "period_start": "2025-04-01", "period_end": "2025-06-30",
    "instant": None, "revenue": 200.0, "net_profit": 20.0, "eps_basic": 1.5,
}
_REC_BS = {
    "context_id": "OneD+OneI", "period_start": "2025-07-01", "period_end": "2025-09-30",
    "instant": None, "revenue": 210.0, "total_assets": 900.0,
    "total_liabilities": 500.0, "total_equity": 400.0,
}


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Tata Consultancy Services", ticker="TCS"))
        self.repos.companies.upsert(Company(name="Infosys", ticker="INFY"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "TCS_consolidated_30-JUN-2025_canonical.json").write_text(json.dumps([_REC_Q1]))
        (self.dir / "TCS_consolidated_30-SEP-2025_canonical.json").write_text(json.dumps([_REC_BS]))
        (self.dir / "INFY_standalone_30-JUN-2025_canonical.json").write_text(
            json.dumps([dict(_REC_Q1, revenue=333.0)])   # distinct bytes -> its own source row
        )
        # a file for a company not in the v2 db -> should be skipped, not crash
        (self.dir / "ZZZZ_consolidated_30-JUN-2025_canonical.json").write_text(json.dumps([_REC_Q1]))

    def test_run(self):
        s = run_backfill(self.repos, self.dir)
        self.assertEqual(s["files"], 4)
        self.assertEqual(s["processed"], 3)
        self.assertEqual(s["skipped"], 1)
        self.assertEqual(s["companies"], ["INFY", "TCS"])
        self.assertGreater(s["facts"], 0)

        cid = self.repos.companies.get_by_ticker("TCS").company_id
        self.assertEqual(
            sorted(self.repos.facts.metrics_for(cid)),
            ["eps_basic", "net_profit", "revenue", "total_assets", "total_equity", "total_liabilities"],
        )
        rev = self.repos.facts.latest(company_id=cid, metric="revenue")
        self.assertEqual(rev.value, 210.0)             # SEP file is the later period
        self.assertEqual(rev.quarter, 2)
        ta = self.repos.facts.get(company_id=cid, metric="total_assets")[0]
        self.assertTrue(ta.is_point_in_time)
        self.assertIsNone(ta.quarter)

    def test_idempotent(self):
        first = run_backfill(self.repos, self.dir)
        cid = self.repos.companies.get_by_ticker("TCS").company_id
        n1 = len(self.repos.facts.get(company_id=cid, metric="revenue"))
        second = run_backfill(self.repos, self.dir)
        n2 = len(self.repos.facts.get(company_id=cid, metric="revenue"))
        self.assertEqual(first["facts"], second["facts"])
        self.assertEqual(n1, n2)
        # source rows de-duped by content hash
        src_count = self.repos.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        self.assertEqual(src_count, 3)

    def test_company_filter_and_limit(self):
        s = run_backfill(self.repos, self.dir, company="TCS")
        self.assertEqual(s["processed"], 2)
        self.assertEqual(s["companies"], ["TCS"])


if __name__ == "__main__":
    unittest.main()
