"""Ratio reconciliation: reported (XBRL) vs computed (engine) ratios."""
from __future__ import annotations

import unittest
from datetime import date

from finqa_v2.models import Basis, Company, FinancialFact, StatementType
from finqa_v2.ratios.reconcile import find_ratio_comparisons
from finqa_v2.sqlite import SqliteRepositories

PL = StatementType.PROFIT_AND_LOSS
BS = StatementType.BALANCE_SHEET
OTHER = StatementType.OTHER
CONS = Basis.CONSOLIDATED

_FY2025 = (date(2024, 4, 1), date(2025, 3, 31))
_FY2026 = (date(2025, 4, 1), date(2026, 3, 31))


def _duration(cid, metric, value, fy, ps, pe, *, stmt=PL):
    return FinancialFact(
        company_id=cid, metric=metric, value=value, unit="INR" if stmt is PL else "x",
        statement_type=stmt, basis=CONS, period_start=ps, period_end=pe,
        financial_year=fy, quarter=None, is_annual=True,
    )


def _instant(cid, metric, value, fy, pe):
    return FinancialFact(
        company_id=cid, metric=metric, value=value, unit="INR", statement_type=BS, basis=CONS,
        period_start=None, period_end=pe, financial_year=fy, quarter=None,
        is_annual=False, is_point_in_time=True,
    )


class TestRatioReconciliation(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.cid = self.repos.companies.upsert(Company(name="Testco", ticker="TEST")).company_id

        facts = [
            # FY2025: debt_to_equity = 200/500 = 0.4, interest_coverage = 150/10 = 15.0
            _duration(self.cid, "pbt_before_exceptional", 150.0, 2025, *_FY2025),
            _duration(self.cid, "finance_costs", 10.0, 2025, *_FY2025),
            _instant(self.cid, "total_equity", 500.0, 2025, _FY2025[1]),
            _instant(self.cid, "borrowings_noncurrent", 200.0, 2025, _FY2025[1]),
            # FY2025 reported ratios: D/E close (matched), ISCR moderately off (small_difference),
            # DSCR reported but has no computed counterpart at all (cannot_compute)
            _duration(self.cid, "debt_equity_ratio_reported", 0.41, 2025, *_FY2025, stmt=OTHER),
            _duration(self.cid, "interest_service_coverage_ratio_reported", 18.0, 2025, *_FY2025, stmt=OTHER),
            _duration(self.cid, "debt_service_coverage_ratio_reported", 1.2, 2025, *_FY2025, stmt=OTHER),

            # FY2026: debt_to_equity = 240/600 = 0.4, interest_coverage = 210/12 = 17.5
            _duration(self.cid, "pbt_before_exceptional", 210.0, 2026, *_FY2026),
            _duration(self.cid, "finance_costs", 12.0, 2026, *_FY2026),
            _instant(self.cid, "total_equity", 600.0, 2026, _FY2026[1]),
            _instant(self.cid, "borrowings_noncurrent", 240.0, 2026, _FY2026[1]),
            # FY2026: no debt_equity_ratio_reported at all (-> missing_reported_ratio, since the
            # company clearly does disclose this ratio, just not this period); ISCR wildly off
            # (-> formula_difference)
            _duration(self.cid, "interest_service_coverage_ratio_reported", 50.0, 2026, *_FY2026, stmt=OTHER),
        ]
        self.repos.facts.add_many(facts)
        self.repos.commit()

        # A second company that never discloses any reported ratio at all.
        self.other_cid = self.repos.companies.upsert(Company(name="NoRatio", ticker="NORATIO")).company_id
        self.repos.facts.add_many([
            _duration(self.other_cid, "pbt_before_exceptional", 90.0, 2025, *_FY2025),
            _duration(self.other_cid, "finance_costs", 5.0, 2025, *_FY2025),
            _instant(self.other_cid, "total_equity", 300.0, 2025, _FY2025[1]),
        ])
        self.repos.commit()

    def _rows(self, ratio: str, **kw) -> list[dict]:
        return [r for r in find_ratio_comparisons(self.repos, **kw) if r["ratio"] == ratio]

    def test_matched_within_tolerance(self):
        rows = self._rows("debt_equity_ratio", company="TEST")
        fy25 = next(r for r in rows if r["financial_year"] == 2025)
        self.assertEqual(fy25["reported_value"], 0.41)
        self.assertAlmostEqual(fy25["computed_value"], 0.4)
        self.assertEqual(fy25["status"], "matched")
        self.assertEqual(fy25["computed_formula"], "total_debt / total_equity")

    def test_missing_reported_ratio_for_a_specific_period(self):
        rows = self._rows("debt_equity_ratio", company="TEST")
        fy26 = next(r for r in rows if r["financial_year"] == 2026)
        self.assertIsNone(fy26["reported_value"])
        self.assertAlmostEqual(fy26["computed_value"], 0.4)
        self.assertEqual(fy26["status"], "missing_reported_ratio")

    def test_small_difference_and_formula_difference(self):
        rows = self._rows("interest_service_coverage_ratio", company="TEST")
        fy25 = next(r for r in rows if r["financial_year"] == 2025)
        fy26 = next(r for r in rows if r["financial_year"] == 2026)
        self.assertEqual(fy25["status"], "small_difference")
        self.assertEqual(fy26["status"], "formula_difference")

    def test_cannot_compute_when_engine_has_no_formula(self):
        rows = self._rows("debt_service_coverage_ratio", company="TEST")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "cannot_compute")
        self.assertIsNone(rows[0]["computed_formula"])

    def test_company_that_never_reports_is_skipped_entirely(self):
        self.assertEqual(find_ratio_comparisons(self.repos, company="NORATIO"), [])

    def test_company_filter_accepts_a_list(self):
        tickers = {r["company"] for r in find_ratio_comparisons(self.repos, company=["TEST", "NORATIO"])}
        self.assertEqual(tickers, {"TEST"})


if __name__ == "__main__":
    unittest.main()
