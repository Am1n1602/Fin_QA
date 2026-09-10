"""Title -> document_type / financial_year / period_label parsing, and end-to-end
ingest of the fixture PDF into an in-memory db."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finqa_v2.documents.pipeline import (
    document_type_of,
    ingest_pdf,
    period_and_fy,
    title_from_filename,
)
from finqa_v2.documents.tests._fixture_pdf import make_results_pdf
from finqa_v2.models import Company
from finqa_v2.sqlite import SqliteRepositories


class TestTitleParsing(unittest.TestCase):
    def test_title_from_filename(self):
        self.assertEqual(
            title_from_filename("2026-04-30T15_41_40.683_Financial_Results_For_The_Quarter_And_Year_Ended_On_31.03.2026.pdf"),
            "Financial Results For The Quarter And Year Ended On 31.03.2026",
        )

    def test_document_type(self):
        self.assertEqual(document_type_of("Financial Results For The Quarter Ended 30.06.2026"), "results_pdf")
        self.assertEqual(document_type_of("Integrated Annual Report 2025-26"), "annual_report")
        self.assertEqual(document_type_of("Q1 FY27 Earnings Call Transcript"), "transcript")

    def test_period_and_fy(self):
        self.assertEqual(period_and_fy("... Ended On 31.03.2026")[1], 2026)
        self.assertEqual(period_and_fy("... Quarter Ended 30.06.2026")[1], 2027)
        self.assertEqual(period_and_fy("Financial Results for the year ended March 31, 2026")[1], 2026)
        self.assertEqual(period_and_fy("Results Q1 FY27")[1], 2027)
        self.assertEqual(period_and_fy("Results FY 2026")[1], 2026)
        self.assertEqual(period_and_fy("Outcome Of Board Meeting"), (None, None))
        # no date in the title -> fall back to the filing timestamp in the filename
        self.assertEqual(
            period_and_fy("Outcome Of Board Meeting",
                          filename="2026-04-30T13_52_59.09_Outcome_Of_Board_Meeting.pdf")[1],
            2027,
        )


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Reliance Industries Ltd.", ticker="RELIANCE"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name) / "RELIANCE"
        d.mkdir()
        self.pdf = make_results_pdf(d / "2026-04-30T10_00_00.0_Audited_Financial_Results_For_The_Quarter_And_Year_Ended_On_31.03.2026.pdf")

    def test_ingest_and_idempotent(self):
        r1 = ingest_pdf(self.pdf, self.repos)
        self.assertEqual(r1["company"], "RELIANCE")
        self.assertEqual(r1["financial_year"], 2026)
        self.assertEqual(r1["document_type"], "results_pdf")
        self.assertEqual(r1["pages"], 3)
        self.assertGreater(r1["chunks"], 0)

        cid = self.repos.companies.get_by_ticker("RELIANCE").company_id
        docs = self.repos.documents.for_company(cid)
        self.assertEqual(len(docs), 1)
        chunks = self.repos.documents.chunks_for(docs[0].document_id)
        self.assertEqual(len(chunks), r1["chunks"])
        self.assertTrue(all(c.financial_year == 2026 for c in chunks))
        self.assertIn("auditors_report", {c.section for c in chunks})

        r2 = ingest_pdf(self.pdf, self.repos)                       # rerun
        self.assertEqual(len(self.repos.documents.for_company(cid)), 1)     # no dup document
        self.assertEqual(self.repos.documents.chunk_count(docs[0].document_id), r2["chunks"])
        self.assertEqual(self.repos.connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 1)

    def test_unknown_company_skipped(self):
        d = Path(self.tmp.name) / "NOPE"
        d.mkdir()
        p = make_results_pdf(d / "x_Financial_Results.pdf")
        r = ingest_pdf(p, self.repos)
        self.assertIn("unknown company", r["skipped"])


if __name__ == "__main__":
    unittest.main()
