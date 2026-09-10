"""SQLite repository round-trips for database.v2. Stdlib unittest.

Run:  python -m unittest database.v2.tests.test_sqlite_repo   (from repo root)
"""
from __future__ import annotations

import unittest
from datetime import date

from database.v2.models import (
    Basis,
    Company,
    DocumentMeta,
    FinancialFact,
    Index,
    IndexMembership,
    MappingConfidence,
    Source,
    StatementType,
)
from database.v2.sqlite import SqliteRepositories


class RepoTestCase(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)


class TestCompanyRepo(RepoTestCase):
    def test_upsert_assigns_id_and_is_idempotent(self):
        a = self.repos.companies.upsert(Company(name="Tata Consultancy Services", ticker="TCS"))
        self.assertIsNotNone(a.company_id)
        b = self.repos.companies.upsert(Company(name="TCS Ltd", ticker="TCS", sector="IT"))
        self.assertEqual(a.company_id, b.company_id)          # same row
        self.assertEqual(b.name, "TCS Ltd")                   # updated
        self.assertEqual(b.sector, "IT")
        self.assertEqual(len(self.repos.companies.list()), 1)

    def test_resolve_by_ticker_alias_and_name(self):
        self.repos.companies.upsert(
            Company(name="LTIMindtree", ticker="LTM", aliases=("LTIM",))
        )
        self.assertEqual(self.repos.companies.resolve("LTM").ticker, "LTM")
        self.assertEqual(self.repos.companies.resolve("ltim").ticker, "LTM")   # alias, case-insensitive
        self.assertEqual(self.repos.companies.resolve("LTIMindtree").ticker, "LTM")
        self.assertIsNone(self.repos.companies.resolve("NOPE"))

    def test_list_filters(self):
        self.repos.companies.upsert(Company(name="A", ticker="A", sector="IT", active=True))
        self.repos.companies.upsert(Company(name="B", ticker="B", sector="Bank", active=False))
        self.assertEqual([c.ticker for c in self.repos.companies.list(active=True)], ["A"])
        self.assertEqual([c.ticker for c in self.repos.companies.list(sector="Bank")], ["B"])


class TestIndexRepo(RepoTestCase):
    def _company(self, ticker):
        return self.repos.companies.upsert(Company(name=ticker, ticker=ticker))

    def test_membership_current_vs_historical(self):
        idx = self.repos.indices.upsert(Index(name="NIFTY 50", provider="NSE"))
        tcs = self._company("TCS")
        old = self._company("YESBANK")
        # TCS: joined 2020-01-01, still a member (valid_to open).
        self.repos.indices.set_membership(
            IndexMembership(index_id=idx.index_id, company_id=tcs.company_id,
                            valid_from=date(2020, 1, 1))
        )
        # YESBANK: member 2018-01-01 .. 2020-03-27, then dropped.
        self.repos.indices.set_membership(
            IndexMembership(
                index_id=idx.index_id, company_id=old.company_id,
                valid_from=date(2018, 1, 1), valid_to=date(2020, 3, 27),
            )
        )
        current = [c.ticker for c in self.repos.indices.members(idx.index_id)]
        self.assertEqual(current, ["TCS"])                                   # valid_to IS NULL only
        self.assertEqual(
            [c.ticker for c in self.repos.indices.members(idx.index_id, on=date(2019, 1, 1))],
            ["YESBANK"],                                                     # TCS not yet in
        )
        self.assertEqual(
            [c.ticker for c in self.repos.indices.members(idx.index_id, on=date(2021, 1, 1))],
            ["TCS"],                                                         # YESBANK already out
        )

    def test_open_ended_membership_is_active_on_any_date(self):
        # valid_from None == "since inception / unknown" -> covers all dates (matches
        # IndexMembership.is_active_on). This is how the Phase 1 backfill records
        # current NIFTY 50 members, since we have no historical join dates.
        idx = self.repos.indices.upsert(Index(name="X"))
        c = self._company("INFY")
        self.repos.indices.set_membership(IndexMembership(idx.index_id, c.company_id))
        self.assertEqual(
            [x.ticker for x in self.repos.indices.members(idx.index_id, on=date(2005, 1, 1))],
            ["INFY"],
        )

    def test_set_membership_idempotent_updates_valid_to(self):
        idx = self.repos.indices.upsert(Index(name="X"))
        c = self._company("C")
        self.repos.indices.set_membership(IndexMembership(idx.index_id, c.company_id))
        self.repos.indices.set_membership(
            IndexMembership(idx.index_id, c.company_id, valid_to=date(2026, 1, 1))
        )
        ms = self.repos.indices.memberships_for(c.company_id)
        self.assertEqual(len(ms), 1)
        self.assertEqual(ms[0].valid_to, date(2026, 1, 1))


class TestSourceRepo(RepoTestCase):
    def test_hash_dedup(self):
        s1 = self.repos.sources.add(Source(kind="xbrl", content_hash="deadbeef"))
        s2 = self.repos.sources.add(Source(kind="xbrl", content_hash="deadbeef", uri="ignored"))
        self.assertEqual(s1.source_id, s2.source_id)
        self.assertEqual(self.repos.sources.get(s1.source_id).kind, "xbrl")


class TestFinancialFactRepo(RepoTestCase):
    def setUp(self):
        super().setUp()
        self.cid = self.repos.companies.upsert(Company(name="TCS", ticker="TCS")).company_id

    def _fact(self, **kw):
        base = dict(
            company_id=self.cid, metric="revenue", value=100.0, unit="INR",
            statement_type=StatementType.PROFIT_AND_LOSS, basis=Basis.CONSOLIDATED,
            period_end=date(2026, 3, 31), financial_year=2026, is_annual=True,
        )
        base.update(kw)
        return FinancialFact(**base)

    def test_add_many_and_latest(self):
        n = self.repos.facts.add_many([
            self._fact(value=90.0, period_end=date(2025, 3, 31), financial_year=2025),
            self._fact(value=100.0, period_end=date(2026, 3, 31), financial_year=2026),
        ])
        self.assertEqual(n, 2)
        latest = self.repos.facts.latest(company_id=self.cid, metric="revenue")
        self.assertEqual(latest.value, 100.0)
        self.assertEqual(latest.period_end, date(2026, 3, 31))
        self.assertEqual(self.repos.facts.metrics_for(self.cid), ["revenue"])

    def test_upsert_on_grain(self):
        self.repos.facts.add_many([self._fact(value=100.0)])
        self.repos.facts.add_many([self._fact(value=105.0)])          # same grain -> update
        got = self.repos.facts.get(company_id=self.cid, metric="revenue")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].value, 105.0)

    def test_missing_value_round_trips_as_none_never_zero(self):
        self.repos.facts.add_many([
            self._fact(
                metric="delta_gross_margin", value=None, unit=None,
                mapping_confidence=MappingConfidence.UNMAPPED,
                mapping_reason="no clean COGS tag for Ind AS IT-services filings",
            )
        ])
        got = self.repos.facts.get(company_id=self.cid, metric="delta_gross_margin")
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0].value)                              # not 0.0
        self.assertTrue(got[0].is_missing)
        # a missing-valued fact is not returned by latest()
        self.assertIsNone(self.repos.facts.latest(company_id=self.cid, metric="delta_gross_margin"))

    def test_zero_is_stored_and_returned_as_zero(self):
        self.repos.facts.add_many([self._fact(metric="exceptional_items", value=0.0)])
        got = self.repos.facts.get(company_id=self.cid, metric="exceptional_items")
        self.assertEqual(got[0].value, 0.0)
        self.assertFalse(got[0].is_missing)


class TestDocumentRepo(RepoTestCase):
    def test_upsert_and_query(self):
        cid = self.repos.companies.upsert(Company(name="TCS", ticker="TCS")).company_id
        d = self.repos.documents.upsert(
            DocumentMeta(company_id=cid, document_type="annual_report",
                         title="TCS Annual Report FY2026", financial_year=2026)
        )
        self.assertIsNotNone(d.document_id)
        d2 = self.repos.documents.upsert(
            DocumentMeta(company_id=cid, document_type="annual_report",
                         title="TCS Annual Report FY2026 (rev)", financial_year=2026,
                         document_id=d.document_id, is_superseded=True)
        )
        self.assertEqual(d2.document_id, d.document_id)
        self.assertTrue(d2.is_superseded)
        self.assertEqual(len(self.repos.documents.for_company(cid, document_type="annual_report")), 1)
        self.assertEqual(len(self.repos.documents.for_company(cid, document_type="transcript")), 0)


class TestProtocolConformance(RepoTestCase):
    def test_runtime_checkable(self):
        from database.v2 import repositories as R
        self.assertIsInstance(self.repos.companies, R.CompanyRepository)
        self.assertIsInstance(self.repos.indices, R.IndexRepository)
        self.assertIsInstance(self.repos.sources, R.SourceRepository)
        self.assertIsInstance(self.repos.facts, R.FinancialFactRepository)
        self.assertIsInstance(self.repos.documents, R.DocumentRepository)


if __name__ == "__main__":
    unittest.main()
