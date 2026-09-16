"""Valuation ratios (§11): price-aligned P/E, P/B, EV/EBITDA, market cap, yields."""
from __future__ import annotations

import unittest
from datetime import date

from finqa_v2.engine import FinancialEngine
from finqa_v2.models import Basis, Company, FinancialFact, SharePrice, StatementType
from finqa_v2.sqlite import SqliteRepositories

PL, BS = StatementType.PROFIT_AND_LOSS, StatementType.BALANCE_SHEET
CONS = Basis.CONSOLIDATED


def _seed(repos):
    cid = repos.companies.upsert(Company(name="Valco", ticker="VAL")).company_id
    facts = []
    for m, v in [("revenue", 1000.0), ("net_profit", 100.0), ("pbt_before_exceptional", 130.0),
                 ("finance_costs", 10.0), ("depreciation", 20.0), ("other_income", 0.0),
                 ("eps_basic", 10.0), ("dividends", 40.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR",
                                   statement_type=PL, basis=CONS,
                                   period_start=date(2025, 4, 1), period_end=date(2026, 3, 31),
                                   financial_year=2026, quarter=None, is_annual=True))
    for m, v in [("total_equity", 500.0), ("total_assets", 1200.0), ("current_liabilities", 200.0),
                 ("cash_and_equivalents", 50.0), ("borrowings_noncurrent", 150.0),
                 ("paid_up_equity_capital", 100.0), ("face_value_per_share", 10.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR",
                                   statement_type=BS, basis=CONS, period_start=None,
                                   period_end=date(2026, 3, 31), financial_year=2026,
                                   quarter=None, is_annual=False, is_point_in_time=True))
    repos.facts.add_many(facts)
    repos.prices.add_prices([SharePrice(cid, date(2026, 3, 27), 200.0)])   # 4 days before FY end
    repos.commit()
    return cid


class TestValuation(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        _seed(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_market_cap_and_pe(self):
        # shares = paid_up 100 / face 10 = 10 ; price 200 -> mcap 2000 ; eps 10 -> pe 20
        mc = self.eng.get_ratio("VAL", "market_cap", period="latest_annual")
        self.assertAlmostEqual(mc.value, 2000.0)
        self.assertEqual(mc.unit, "INR")
        pe = self.eng.get_ratio("VAL", "pe", period="latest_annual")
        self.assertAlmostEqual(pe.value, 20.0)
        self.assertEqual(pe.unit, "x")
        self.assertIn("share_price", pe.components)

    def test_pb_and_yields(self):
        pb = self.eng.get_ratio("VAL", "pb", period="latest_annual")     # 2000 / 500
        self.assertAlmostEqual(pb.value, 4.0)
        ey = self.eng.get_ratio("VAL", "earnings_yield", period="latest_annual")  # 10/200*100
        self.assertAlmostEqual(ey.value, 5.0)
        dy = self.eng.get_ratio("VAL", "dividend_yield", period="latest_annual")  # (40/10)/200*100
        self.assertAlmostEqual(dy.value, 2.0)

    def test_ev_ebitda(self):
        # ebitda = pbt_before_exc 130 + dep 20 + fin 10 - other_income 0 = 160
        # net_debt = borrowings 150 - cash 50 = 100 ; ev = 2000 + 100 = 2100 ; /160
        ev = self.eng.get_ratio("VAL", "ev_ebitda", period="latest_annual")
        self.assertAlmostEqual(ev.value, 2100.0 / 160.0, places=4)

    def test_missing_price_returns_none_with_limitation(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        _seed(repos)
        # wipe prices
        repos.connection.execute("DELETE FROM share_prices")
        repos.commit()
        r = FinancialEngine(repos).get_ratio("VAL", "pe", period="latest_annual")
        self.assertIsNone(r.value)
        self.assertTrue(any("no share price" in l for l in r.limitations))

    def test_get_valuation_alias_and_compare(self):
        self.assertAlmostEqual(self.eng.get_valuation("VAL", "p/e").value, 20.0)
        cc = self.eng.compare_companies("pe", ["VAL"], period="latest_annual")
        self.assertEqual(cc["kind"], "ratio")
        self.assertEqual(cc["results"][0]["ticker"], "VAL")

    def test_unknown_valuation_metric(self):
        r = self.eng.get_valuation("VAL", "peg")
        self.assertIsNone(r.value)
        self.assertTrue(any("unknown valuation metric" in l for l in r.limitations))


def _seed_bank(repos):
    cid = repos.companies.upsert(Company(name="Bankco", ticker="BNK",
                                         sector="Financial Services")).company_id
    facts = []
    for m, v in [("net_profit", 200.0), ("pbt", 260.0), ("bank_operating_profit", 400.0),
                 ("bank_provisions", 60.0), ("dividends", 50.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR",
                                   statement_type=PL, basis=CONS,
                                   period_start=date(2025, 4, 1), period_end=date(2026, 3, 31),
                                   financial_year=2026, quarter=None, is_annual=True))
    for m, v in [("total_equity", 1000.0), ("total_assets", 20000.0),
                 ("paid_up_equity_capital", 20.0), ("face_value_per_share", 2.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR", statement_type=BS,
                                   basis=CONS, period_start=None, period_end=date(2026, 3, 31),
                                   financial_year=2026, quarter=None, is_annual=False,
                                   is_point_in_time=True))
    repos.facts.add_many(facts)
    repos.prices.add_prices([SharePrice(cid, date(2026, 3, 28), 300.0)])
    repos.commit()


def _seed_insurer(repos):
    cid = repos.companies.upsert(Company(name="Lifeco", ticker="LIFE",
                                         sector="Financial Services")).company_id
    facts = []
    for m, v in [("net_profit", 50.0), ("total_expenses", 2400.0), ("total_income", 2500.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR", statement_type=PL,
                                   basis=CONS, period_start=date(2025, 4, 1),
                                   period_end=date(2026, 3, 31), financial_year=2026,
                                   quarter=None, is_annual=True))
    for m, v in [("total_equity", 500.0), ("total_assets", 10000.0)]:
        facts.append(FinancialFact(company_id=cid, metric=m, value=v, unit="INR", statement_type=BS,
                                   basis=CONS, period_start=None, period_end=date(2026, 3, 31),
                                   financial_year=2026, quarter=None, is_annual=False,
                                   is_point_in_time=True))
    repos.facts.add_many(facts)
    repos.commit()


class TestBankValuation(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        _seed_bank(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_pe_from_net_profit_when_no_reported_eps(self):
        # shares = 20 / 2 = 10 ; mcap = 300 * 10 = 3000 ; P/E = 3000 / 200 = 15
        pe = self.eng.get_ratio("BNK", "pe", period="latest_annual")
        self.assertAlmostEqual(pe.value, 15.0)
        self.assertTrue(any("EPS derived" in l for l in pe.limitations))

    def test_ev_ebitda_uses_ppop_proxy(self):
        # mcap 3000 / bank_operating_profit 400 = 7.5
        ev = self.eng.get_ratio("BNK", "ev_ebitda", period="latest_annual")
        self.assertAlmostEqual(ev.value, 7.5)
        self.assertTrue(any("PPOP" in l or "pre-provision" in l for l in ev.limitations))


class TestInsurerRatios(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        _seed_insurer(self.repos)
        self.eng = FinancialEngine(self.repos)

    def test_margin_uses_total_income_topline(self):
        # net_profit 50 / total_income 2500 = 2%
        m = self.eng.get_ratio("LIFE", "net_profit_margin", period="latest_annual")
        self.assertAlmostEqual(m.value, 2.0)

    def test_roe_and_dupont(self):
        roe = self.eng.get_ratio("LIFE", "roe", period="latest_annual")
        self.assertAlmostEqual(roe.value, 10.0)                      # 50 / 500
        d = self.eng.decompose_metric("LIFE", "roe", period="latest_annual")
        comps = d.components.get("components") or {}
        self.assertAlmostEqual(comps["net_profit_margin"], 2.0)
        self.assertAlmostEqual(comps["asset_turnover"], 0.25)       # 2500 / 10000
        self.assertAlmostEqual(comps["equity_multiplier"], 20.0)    # 10000 / 500


if __name__ == "__main__":
    unittest.main()
