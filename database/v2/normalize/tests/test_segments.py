"""Segment extraction from raw XBRL facts."""
from __future__ import annotations

import unittest
from datetime import date

from database.v2.models import Company
from database.v2.normalize.segments import extract_and_store, extract_segments
from database.v2.sqlite import SqliteRepositories


def _fact(tag, value, ctx, ps, pe):
    return {"line_item_tag": f"in-capmkt:{tag}", "value": value, "context_id": ctx,
            "period_start": ps, "period_end": pe, "instant": None}


RAW = [
    # current quarter (One*) -- 3 segments
    _fact("DescriptionOfReportableSegment", "Oil to Chemicals (O2C)", "OneReportable1D", "2026-01-01", "2026-03-31"),
    _fact("SegmentRevenue", "1849440000000", "OneReportable1D", "2026-01-01", "2026-03-31"),
    _fact("DescriptionOfReportableSegment", "Retail", "OneReportable2D", "2026-01-01", "2026-03-31"),
    _fact("SegmentRevenue", "984570000000", "OneReportable2D", "2026-01-01", "2026-03-31"),
    _fact("DescriptionOfReportableSegment", "Digital Services", "OneReportable3D", "2026-01-01", "2026-03-31"),
    _fact("SegmentRevenue", "459450000000", "OneReportable3D", "2026-01-01", "2026-03-31"),
    # full year (Four*) -- same 3 segments
    _fact("DescriptionOfReportableSegment", "Oil to Chemicals (O2C)", "FourReportable1D", "2025-04-01", "2026-03-31"),
    _fact("SegmentRevenue", "6624010000000", "FourReportable1D", "2025-04-01", "2026-03-31"),
    _fact("DescriptionOfReportableSegment", "Retail", "FourReportable2D", "2025-04-01", "2026-03-31"),
    _fact("SegmentRevenue", "3710850000000", "FourReportable2D", "2025-04-01", "2026-03-31"),
    _fact("DescriptionOfReportableSegment", "Digital Services", "FourReportable3D", "2025-04-01", "2026-03-31"),
    _fact("SegmentRevenue", "1761640000000", "FourReportable3D", "2025-04-01", "2026-03-31"),
    # noise: sub-breakdown context (no name), and a Finance context, and whole-company
    _fact("SegmentAssets", "999", "OneReportable31D", "2026-01-01", "2026-03-31"),
    _fact("SegmentFinanceCosts", "12", "OneReportableFinance1D", "2026-01-01", "2026-03-31"),
    _fact("RevenueFromOperations", "3118500000000", "OneD", "2026-01-01", "2026-03-31"),
]


class TestExtractSegments(unittest.TestCase):
    def test_shapes(self):
        segs, named = extract_segments(RAW, company_id=1, basis="consolidated")
        self.assertEqual({s.name for s in segs}, {"Oil to Chemicals (O2C)", "Retail", "Digital Services"})
        self.assertEqual({s.slug for s in segs}, {"oil_to_chemicals_o2c", "retail", "digital_services"})
        # 3 segments x 2 periods x 1 metric each
        self.assertEqual(len(named), 6)
        self.assertTrue(all(f.metric == "segment_revenue" for _, f in named))

    def test_period_derivation(self):
        _, named = extract_segments(RAW, company_id=1, basis="consolidated")
        by = {(n, f.is_annual): f for n, f in named}
        q = by[("Retail", False)]
        self.assertEqual(q.quarter, 4)
        self.assertEqual(q.financial_year, 2026)
        self.assertEqual(q.value, 984570000000.0)
        y = by[("Retail", True)]
        self.assertIsNone(y.quarter)
        self.assertTrue(y.is_annual)
        self.assertEqual(y.period_start, date(2025, 4, 1))

    def test_noise_contexts_excluded(self):
        segs, named = extract_segments(RAW, company_id=1, basis="consolidated")
        self.assertNotIn("segment_assets", {f.metric for _, f in named})     # OneReportable31D had no name
        self.assertEqual(len(segs), 3)


class TestExtractAndStore(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Reliance Industries Ltd.", ticker="RELIANCE"))

    def test_store_and_idempotent(self):
        import json, tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp())
        p = d / "RELIANCE_consolidated_31-MAR-2026_facts_raw.json"
        p.write_text(json.dumps(RAW))

        r1 = extract_and_store(p, self.repos)
        self.assertEqual(r1["segments"], 3)
        self.assertEqual(r1["facts"], 6)
        cid = self.repos.companies.get_by_ticker("RELIANCE").company_id
        self.assertEqual(len(self.repos.segments.segments_for(cid)), 3)

        r2 = extract_and_store(p, self.repos)               # rerun
        self.assertEqual(r2["facts"], 6)
        self.assertEqual(len(self.repos.segments.segments_for(cid)), 3)
        rows = self.repos.segments.list_segment_facts(cid, metric="segment_revenue")
        self.assertEqual(len(rows), 6)
        src = self.repos.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        self.assertEqual(src, 1)


if __name__ == "__main__":
    unittest.main()
