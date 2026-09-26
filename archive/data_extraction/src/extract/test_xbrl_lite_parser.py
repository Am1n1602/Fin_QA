import unittest
from pathlib import Path

from src.extract.xbrl_lite_parser import _add_months, _derive_quarter_period, parse_xbrl_file

RAW = Path(__file__).resolve().parents[4] / "data_extraction" / "data" / "raw"


class DeriveQuarterPeriod(unittest.TestCase):
    def test_first_quarter(self):
        self.assertEqual(_derive_quarter_period("2019-04-01", "First quarter", "2019-06-30"),
                          ("2019-04-01", "2019-06-30"))

    def test_half_yearly_label_is_still_a_discrete_quarter(self):
        self.assertEqual(_derive_quarter_period("2019-04-01", "Half yearly", "2019-09-30"),
                          ("2019-07-01", "2019-09-30"))

    def test_third_quarter(self):
        self.assertEqual(_derive_quarter_period("2019-04-01", "Third quarter", "2019-12-31"),
                          ("2019-10-01", "2019-12-31"))

    def test_yearly_label_is_the_q4_quarter_not_the_full_year(self):
        self.assertEqual(_derive_quarter_period("2019-04-01", "Yearly", "2020-03-31"),
                          ("2020-01-01", "2020-03-31"))

    def test_fourth_quarter_same_as_yearly(self):
        self.assertEqual(_derive_quarter_period("2019-04-01", "Fourth quarter", "2020-03-31"),
                          ("2020-01-01", "2020-03-31"))

    def test_calendar_fiscal_year_start(self):
        # NESTLEIND-style Jan-Dec fiscal year -- offset is relative to fy_start, not April
        self.assertEqual(_derive_quarter_period("2023-01-01", "Fourth quarter", "2023-12-31"),
                          ("2023-10-01", "2023-12-31"))

    def test_mismatched_end_date_fails_safe(self):
        # end date doesn't land on the derived quarter's last day -> no override
        self.assertIsNone(_derive_quarter_period("2019-04-01", "First quarter", "2019-06-29"))

    def test_no_quarter_label_fails_safe(self):
        # the true annual/year-to-date context (e.g. "FourD") has no ReportingQuarter
        # of its own -- must not be guessed at
        self.assertIsNone(_derive_quarter_period("2019-04-01", None, "2019-03-31"))

    def test_missing_inputs_fail_safe(self):
        self.assertIsNone(_derive_quarter_period(None, "First quarter", "2019-06-30"))
        self.assertIsNone(_derive_quarter_period("2019-04-01", "First quarter", None))


class AddMonths(unittest.TestCase):
    def test_within_year(self):
        from datetime import date
        self.assertEqual(_add_months(date(2019, 4, 1), 3), date(2019, 7, 1))

    def test_crosses_year_boundary(self):
        from datetime import date
        self.assertEqual(_add_months(date(2019, 4, 1), 9), date(2020, 1, 1))


@unittest.skipUnless((RAW / "HDFCBANK").exists(), "HDFCBANK raw XBRL not available locally")
class HdfcbankRealFiling(unittest.TestCase):
    """Regression test for the real bug: HDFCBANK's 'OneD' context is never declared
    in <context> and omits DateOfStartOfReportingPeriod, so every fact under it used
    to get period_start=None and get silently dropped downstream (confirmed: 0 records
    in the canonical output before this fix)."""

    def test_quarterly_filing_gets_a_real_period(self):
        recs = parse_xbrl_file(
            str(RAW / "HDFCBANK" / "30-Jun-2019_Financial_Results_Original_Consolidated.xbrl"),
            "HDFCBANK")
        hits = [r for r in recs
                if r["line_item_tag"] == "in-bse-fin:InterestEarned" and r["context_id"] == "OneD"]
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["period_start"], "2019-04-01")
        self.assertEqual(hits[0]["period_end"], "2019-06-30")

    def test_annual_filing_q4_context_resolved_but_ytd_context_stays_unresolved(self):
        recs = parse_xbrl_file(
            str(RAW / "HDFCBANK" / "31-Mar-2020_Financial_Results_Original_Consolidated.xbrl"),
            "HDFCBANK")
        by_ctx = {(r["line_item_tag"], r["context_id"]): r for r in recs}
        q4 = by_ctx[("in-bse-fin:InterestEarned", "OneD")]
        self.assertEqual((q4["period_start"], q4["period_end"]), ("2020-01-01", "2020-03-31"))
        ytd = by_ctx[("in-bse-fin:InterestEarned", "FourD")]
        self.assertIsNone(ytd["period_start"])  # Phase 2, deliberately not recovered


@unittest.skipUnless((RAW / "TCS").exists(), "TCS raw XBRL not available locally")
class NonBankFilingsUnaffected(unittest.TestCase):
    """TCS already self-declares both start and end -- confirms the new fallback
    never overrides an already-resolvable context."""

    def test_annual_filing_dates_unchanged(self):
        recs = parse_xbrl_file(
            str(RAW / "TCS" / "31-Mar-2019_Financial_Results_Original_Consolidated.xbrl"), "TCS")
        by_ctx = {(r["line_item_tag"], r["context_id"]): r for r in recs}
        q4 = by_ctx[("in-bse-fin:Income", "OneD")]
        self.assertEqual((q4["period_start"], q4["period_end"]), ("2019-01-01", "2019-03-31"))
        ytd = by_ctx[("in-bse-fin:Income", "FourD")]
        self.assertEqual((ytd["period_start"], ytd["period_end"]), ("2018-04-01", "2019-03-31"))


if __name__ == "__main__":
    unittest.main()
