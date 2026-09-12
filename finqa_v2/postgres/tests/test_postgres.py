"""PostgreSQL backend parity (§17). Gated on FINQA_PG_URL -- skips with no Postgres.

    docker compose -f deployment/compose/pgvector.yml up -d   # needs POSTGRES_PASSWORD set, see .env.example
    set FINQA_PG_URL=postgresql://finqa:<POSTGRES_PASSWORD>@localhost:55432/finqa
    python -m unittest finqa_v2.postgres.tests.test_postgres
"""
from __future__ import annotations

import os
import unittest
from datetime import date

from finqa_v2.engine import FinancialEngine
from finqa_v2.engine.tests._fixture import seed as seed_engine
from finqa_v2.models import (
    Basis,
    Company,
    FinancialFact,
    Index,
    IndexMembership,
    SharePrice,
    Source,
    StatementType,
)
from finqa_v2.repositories import (
    CompanyRepository,
    DocumentRepository,
    FinancialFactRepository,
    IndexRepository,
    SegmentRepository,
    SharePriceRepository,
    SourceRepository,
)
from finqa_v2.sqlite import SqliteRepositories

_URL = os.environ.get("FINQA_PG_URL") or os.environ.get("DATABASE_URL")


def _fresh_pg():
    from finqa_v2.postgres import PgRepositories

    r = PgRepositories(_URL)
    with r._raw.cursor() as cur:                      # empty every table for a clean test
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    r._raw.commit()
    r.close()
    return PgRepositories(_URL)


@unittest.skipUnless(_URL, "set FINQA_PG_URL to run the Postgres backend tests")
class TestPgBackend(unittest.TestCase):
    def setUp(self):
        self.r = _fresh_pg()
        self.addCleanup(self.r.close)

    def test_protocol_conformance(self):
        for repo, proto in [
            (self.r.companies, CompanyRepository), (self.r.indices, IndexRepository),
            (self.r.sources, SourceRepository), (self.r.facts, FinancialFactRepository),
            (self.r.segments, SegmentRepository), (self.r.prices, SharePriceRepository),
            (self.r.documents, DocumentRepository),
        ]:
            self.assertIsInstance(repo, proto)

    def test_company_upsert_resolve_idempotent(self):
        c = self.r.companies.upsert(Company(name="Testco", ticker="TEST", aliases=("TESTCO",)))
        self.assertEqual(self.r.companies.upsert(Company(name="Testco", ticker="TEST")).company_id,
                         c.company_id)
        self.assertEqual(self.r.companies.resolve("test").ticker, "TEST")     # ILIKE
        self.assertEqual(self.r.companies.resolve("testco").ticker, "TEST")   # alias

    def test_fact_grain_upsert_and_missing_is_null(self):
        cid = self.r.companies.upsert(Company(name="T", ticker="TEST")).company_id
        f = dict(company_id=cid, unit="INR", statement_type=StatementType.PROFIT_AND_LOSS,
                 basis=Basis.CONSOLIDATED, period_start=date(2025, 4, 1),
                 period_end=date(2026, 3, 31), financial_year=2026, is_annual=True)
        self.r.facts.add_many([FinancialFact(metric="revenue", value=1000.0, **f)])
        self.r.facts.add_many([FinancialFact(metric="revenue", value=1200.0, **f)])   # same grain
        got = self.r.facts.get(company_id=cid, metric="revenue")
        self.assertEqual([x.value for x in got], [1200.0])
        self.r.facts.add_many([FinancialFact(metric="ebitda", value=None, **f)])
        self.assertEqual([x.value for x in self.r.facts.get(company_id=cid, metric="ebitda")], [None])
        self.assertIsNone(self.r.facts.latest(company_id=cid, metric="ebitda"))

    def test_source_hash_dedup_and_prices(self):
        s1 = self.r.sources.add(Source(kind="xbrl", content_hash="h1", document_title="a"))
        s2 = self.r.sources.add(Source(kind="xbrl", content_hash="h1", document_title="a"))
        self.assertEqual(s1.source_id, s2.source_id)
        cid = self.r.companies.upsert(Company(name="T", ticker="TEST")).company_id
        self.r.prices.add_prices([SharePrice(cid, date(2026, 3, 30), 200.0)])
        self.assertEqual(self.r.prices.on_or_before(cid, date(2026, 3, 31)).close, 200.0)
        self.assertIsNone(self.r.prices.on_or_before(cid, date(2026, 6, 1)))          # >14 days

    def test_membership_current_vs_historical(self):
        c1 = self.r.companies.upsert(Company(name="A", ticker="AAA")).company_id
        c2 = self.r.companies.upsert(Company(name="B", ticker="BBB")).company_id
        idx = self.r.indices.upsert(Index(name="NIFTY 50", provider="NSE"))
        self.r.indices.set_membership(IndexMembership(idx.index_id, c1))
        self.r.indices.set_membership(IndexMembership(idx.index_id, c2, valid_to=date(2025, 1, 1)))
        self.assertEqual([m.ticker for m in self.r.indices.members(idx.index_id)], ["AAA"])

    def test_engine_runs_unchanged_on_postgres(self):
        """The §17 claim: nothing above the repository layer changes."""
        seed_engine(self.r)                          # the SAME fixture the SQLite engine tests use
        pg = FinancialEngine(self.r)

        sq = SqliteRepositories(":memory:")
        self.addCleanup(sq.close)
        seed_engine(sq)
        sl = FinancialEngine(sq)

        for call in (lambda e: e.get_metric("TEST", "revenue", period="FY2026").value,
                     lambda e: e.get_ratio("TEST", "roe", period="FY2026").value,
                     lambda e: e.get_growth("TEST", "revenue", kind="yoy").value,
                     lambda e: e.decompose_metric("TEST", "roe", period="FY2026").value):
            self.assertAlmostEqual(call(pg), call(sl), places=6)


@unittest.skipUnless(_URL, "set FINQA_PG_URL")
class TestRepositoriesFromEnv(unittest.TestCase):
    def test_factory_picks_postgres(self):
        from finqa_v2.db import repositories_from_env
        from finqa_v2.postgres import PgRepositories

        r = repositories_from_env()
        self.addCleanup(r.close)
        self.assertIsInstance(r, PgRepositories)


if __name__ == "__main__":
    unittest.main()
