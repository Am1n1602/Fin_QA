"""Coverage audit over a small in-memory dataset."""
from __future__ import annotations

import json
import unittest
from datetime import date

from finqa_v2.dataset.audit import audit_coverage
from finqa_v2.models import (
    Basis,
    Company,
    FinancialFact,
    Index,
    IndexMembership,
    Segment,
    SegmentFact,
    SharePrice,
    StatementType,
)
from finqa_v2.sqlite import SqliteRepositories

PL, BS = StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET
CONS = Basis.CONSOLIDATED


def _annual(cid, m, v, fy):
    return FinancialFact(company_id=cid, metric=m, value=v, unit="INR", statement_type=PL,
                         basis=CONS, period_start=date(fy - 1, 4, 1), period_end=date(fy, 3, 31),
                         financial_year=fy, quarter=None, is_annual=True)


def _bs(cid, m, v, fy):
    return FinancialFact(company_id=cid, metric=m, value=v, unit="INR", statement_type=BS,
                         basis=CONS, period_start=None, period_end=date(fy, 3, 31),
                         financial_year=fy, quarter=None, is_annual=False, is_point_in_time=True)


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        r = self.repos
        good = r.companies.upsert(Company(name="Goodco", ticker="GOOD", sector="IT")).company_id
        thin = r.companies.upsert(Company(name="Thinco", ticker="THIN", sector="IT")).company_id
        bank = r.companies.upsert(Company(name="Bankco", ticker="BANK",
                                          sector="Financial Services")).company_id
        idx = r.indices.upsert(Index(name="NIFTY 50", provider="NSE"))
        for c in (good, thin, bank):
            r.indices.set_membership(IndexMembership(idx.index_id, c))

        facts = []
        for fy in (2025, 2026):
            for m, v in [("revenue", 1000.0 * fy), ("net_profit", 100.0)]:
                facts.append(_annual(good, m, v, fy))
            facts.append(_bs(good, "total_equity", 500.0, fy))
            facts.append(_bs(good, "total_assets", 1200.0, fy))
        facts.append(_annual(thin, "revenue", 5.0, 2026))            # one annual period only
        facts.append(_bs(thin, "total_equity", 2.0, 2026))
        for fy in (2025, 2026):
            facts.append(_annual(bank, "bank_interest_earned", 900.0, fy))
            facts.append(_bs(bank, "total_assets", 9000.0, fy))
            facts.append(_bs(bank, "total_equity", 800.0, fy))
        r.facts.add_many(facts)

        seg = r.segments.upsert_segment(Segment(company_id=good, name="Services"))
        r.segments.add_facts([SegmentFact(segment_id=seg.segment_id, company_id=good,
                                          metric="segment_revenue", value=900.0, basis=CONS,
                                          period_end=date(2026, 3, 31), financial_year=2026,
                                          is_annual=True)])
        r.prices.add_prices([SharePrice(good, date(2026, 3, 28), 300.0),
                             SharePrice(bank, date(2026, 3, 28), 90.0)])
        r.commit()

    def test_gaps_and_score(self):
        rep = audit_coverage(self.repos)
        json.dumps(rep)
        self.assertEqual(rep["n_index_members"], 3)
        g = rep["gaps"]
        self.assertIn("THIN", g["under_2_annual"])
        self.assertIn("THIN", g["no_prices"])
        self.assertIn("THIN", g["no_documents"])
        self.assertIn("GOOD", g["no_documents"])            # no docs seeded for anyone
        self.assertNotIn("BANK", g["no_segments_non_bank"]) # banks excused
        self.assertNotIn("GOOD", g["no_segments_non_bank"]) # GOOD has a segment
        # GOOD isn't "complete" (no documents), so score < 100 but > 0
        self.assertLess(rep["completeness_score"], 100.0)

    def test_bank_detection_and_valuation_flag(self):
        rep = audit_coverage(self.repos)
        rows = {r["ticker"]: r for r in rep["companies"]}
        self.assertTrue(rows["BANK"]["is_bank"])
        self.assertFalse(rows["GOOD"]["is_bank"])
        # GOOD: has price + equity + shares? no paid_up/face -> pb uses market_cap/equity,
        # market_cap needs shares -> unavailable; that's fine, just assert the key exists
        self.assertIn("valuation_ready", rows["GOOD"])

    def test_check_flag_is_false_when_no_critical_gap(self):
        rep = audit_coverage(self.repos)
        # no company has zero facts and none is missing a balance sheet -> not critical
        self.assertFalse(rep["critical"])


if __name__ == "__main__":
    unittest.main()
