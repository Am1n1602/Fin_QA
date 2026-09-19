"""run_backfill's per-company commit checkpointing (an interrupted run should lose at
most the company in flight, not every already-ingested company -- see the abandoned
v2.2 postmortem's finding that a single end-of-run commit lost an entire multi-hour
PDF backfill when the process was stopped partway through)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from finqa_v2.documents.backfill import _pdfs, run_backfill
from finqa_v2.documents.tests._fixture_pdf import make_results_pdf
from finqa_v2.models import Company
from finqa_v2.sqlite import SqliteRepositories


class TestCommitCheckpointing(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Reliance Industries Ltd.", ticker="RELIANCE"))
        self.repos.companies.upsert(Company(name="Tata Consultancy Services", ticker="TCS"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        raw = Path(self.tmp.name)
        # two PDFs per company -- filenames sort before/after within each company dir
        for tkr, n in (("RELIANCE", 2), ("TCS", 2)):
            d = raw / tkr
            d.mkdir()
            for i in range(n):
                make_results_pdf(d / f"2026-0{i + 1}-01T10_00_00.0_Financial_Results.pdf")
        self.raw = raw

    def test_commits_once_per_company_not_once_for_the_whole_run(self):
        with patch.object(self.repos, "commit", wraps=self.repos.commit) as spy:
            s = run_backfill(self.repos, self.raw)
        self.assertEqual(spy.call_count, 2)              # one per company, not one total
        self.assertEqual(s["companies"], ["RELIANCE", "TCS"])
        self.assertEqual(s["ingested"], 4)

    def test_data_ingested_matches_a_single_final_commit_result(self):
        run_backfill(self.repos, self.raw)
        rel = self.repos.companies.get_by_ticker("RELIANCE").company_id
        tcs = self.repos.companies.get_by_ticker("TCS").company_id
        self.assertEqual(len(self.repos.documents.for_company(rel)), 2)
        self.assertEqual(len(self.repos.documents.for_company(tcs)), 2)


class TestCompanySubsetting(unittest.TestCase):
    """A pilot run on a subset of companies -- the same mechanism that later scales to
    the full universe just by widening the list."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.repos.companies.upsert(Company(name="Reliance Industries Ltd.", ticker="RELIANCE"))
        self.repos.companies.upsert(Company(name="Tata Consultancy Services", ticker="TCS"))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        raw = Path(self.tmp.name)
        for tkr, n in (("RELIANCE", 2), ("TCS", 2)):
            d = raw / tkr
            d.mkdir()
            for i in range(n):
                make_results_pdf(d / f"2026-0{i + 1}-01T10_00_00.0_Financial_Results.pdf")
        self.raw = raw

    def test_pdfs_a_single_ticker_string_is_still_accepted(self):
        files = _pdfs(self.raw, "TCS")
        self.assertTrue(all(p.parent.name == "TCS" for p in files))
        self.assertEqual(len(files), 2)

    def test_pdfs_list_of_tickers_scopes_to_exactly_those(self):
        files = _pdfs(self.raw, ["TCS"])
        self.assertEqual({p.parent.name for p in files}, {"TCS"})

    def test_run_backfill_with_a_company_list_ingests_only_those(self):
        s = run_backfill(self.repos, self.raw, company=["TCS"])
        self.assertEqual(s["companies"], ["TCS"])
        rel = self.repos.companies.get_by_ticker("RELIANCE").company_id
        self.assertEqual(len(self.repos.documents.for_company(rel)), 0)


if __name__ == "__main__":
    unittest.main()
