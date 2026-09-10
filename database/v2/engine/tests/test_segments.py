"""SegmentEngine: contribution %, YoY growth, share-of-total-change."""
from __future__ import annotations

import unittest
from datetime import date

from database.v2.engine.segments import SegmentEngine
from database.v2.models import Basis, Company, Segment, SegmentFact
from database.v2.sqlite import SqliteRepositories

CONS = Basis.CONSOLIDATED


def _sf(sid, cid, value, fy, *, annual):
    return SegmentFact(
        segment_id=sid, company_id=cid, metric="segment_revenue", value=value, basis=CONS,
        period_start=date(fy - 1, 4, 1), period_end=date(fy, 3, 31),
        financial_year=fy, quarter=None, is_annual=annual,
    )


class TestSegmentEngine(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.cid = self.repos.companies.upsert(Company(name="Testco", ticker="TEST")).company_id
        self.a = self.repos.segments.upsert_segment(Segment(self.cid, "Alpha")).segment_id
        self.b = self.repos.segments.upsert_segment(Segment(self.cid, "Beta")).segment_id
        self.c = self.repos.segments.upsert_segment(Segment(self.cid, "Gamma")).segment_id
        # FY2025 totals 1000 (600/300/100); FY2026 totals 1300 (700/450/150) -> +300
        self.repos.segments.add_facts([
            _sf(self.a, self.cid, 600.0, 2025, annual=True),
            _sf(self.b, self.cid, 300.0, 2025, annual=True),
            _sf(self.c, self.cid, 100.0, 2025, annual=True),
            _sf(self.a, self.cid, 700.0, 2026, annual=True),
            _sf(self.b, self.cid, 450.0, 2026, annual=True),
            _sf(self.c, self.cid, 150.0, 2026, annual=True),
        ])
        self.repos.commit()
        self.eng = SegmentEngine(self.repos)

    def test_get_segment_data_contributions(self):
        r = self.eng.get_segment_data("TEST", period="latest_annual")
        self.assertTrue(r.ok)
        self.assertEqual([row.segment for row in r.rows], ["Alpha", "Beta", "Gamma"])   # sorted by revenue desc
        self.assertEqual(r.total_revenue, 1300.0)
        self.assertAlmostEqual(sum(row.contribution_pct for row in r.rows), 100.0)
        self.assertAlmostEqual(r.rows[0].contribution_pct, 700 / 1300 * 100)
        self.assertTrue(any("margin not available" in x for x in r.limitations))

    def test_get_segment_data_specific_fy(self):
        r = self.eng.get_segment_data("TEST", period="FY2025")
        self.assertEqual(r.total_revenue, 1000.0)
        self.assertAlmostEqual(r.rows[0].contribution_pct, 60.0)

    def test_segment_growth_attribution(self):
        r = self.eng.segment_growth("TEST", kind="yoy")
        self.assertTrue(r.ok)
        self.assertEqual(r.total_change, 300.0)
        by = {row.segment: row for row in r.rows}
        self.assertEqual(by["Alpha"].abs_change, 100.0)
        self.assertEqual(by["Beta"].abs_change, 150.0)
        self.assertEqual(by["Gamma"].abs_change, 50.0)
        self.assertAlmostEqual(by["Beta"].share_of_total_change_pct, 50.0)   # 150/300
        self.assertAlmostEqual(sum(row.share_of_total_change_pct for row in r.rows), 100.0)
        self.assertAlmostEqual(by["Alpha"].growth_pct, 100 / 600 * 100)
        # ordered by biggest absolute contributor
        self.assertEqual(r.rows[0].segment, "Beta")

    def test_unknown_company(self):
        r = self.eng.get_segment_data("NOPE")
        self.assertFalse(r.ok)
        self.assertTrue(r.limitations)

    def test_no_segments(self):
        self.repos.companies.upsert(Company(name="Plainco", ticker="PLAIN"))
        r = self.eng.get_segment_data("PLAIN")
        self.assertFalse(r.ok)
        self.assertIn("single-segment or not disclosed", r.limitations[0])


if __name__ == "__main__":
    unittest.main()
