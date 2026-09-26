import unittest
from unittest.mock import patch

from src.fetch.historical_xbrl_backfill import backfill_company


class InsuranceIndexFallback(unittest.TestCase):
    """Regression test for the real bug: HDFCLIFE/SBILIFE return 0 records under NSE's
    default "equities" index for any date range (not a listing-date issue -- both listed
    in 2017), because insurers file under a separate "insurance" index category."""

    def test_falls_back_to_insurance_index_when_equities_is_empty(self):
        calls = []

        def fake_fetch(symbol, from_date, to_date, period="Annual", index="equities"):
            calls.append((period, index))
            if index == "equities":
                return []
            return [{
                "xbrl": "https://example.test/real.xml",
                "consolidated": "Non-Consolidated",
                "periodEnd": "31-Dec-2024",
            }]

        with patch("src.fetch.historical_xbrl_backfill.nse_source.fetch_historical_financial_results",
                   side_effect=fake_fetch), \
             patch("src.fetch.historical_xbrl_backfill.pdf_downloader.download_filing",
                   return_value=True) as mock_download:
            downloaded = backfill_company("HDFCLIFE")

        self.assertEqual(downloaded, 2)  # one per period (Annual, Quarterly)
        # each period tried "equities" first, then "insurance" as a fallback
        self.assertEqual(calls, [("Annual", "equities"), ("Annual", "insurance"),
                                  ("Quarterly", "equities"), ("Quarterly", "insurance")])
        # filing_period falls back to periodEnd when toDate/financialYear are absent
        for call in mock_download.call_args_list:
            self.assertEqual(call.kwargs["period"], "31-Dec-2024")

    def test_no_fallback_when_equities_already_has_records(self):
        def fake_fetch(symbol, from_date, to_date, period="Annual", index="equities"):
            if index == "equities":
                return [{"xbrl": "https://example.test/real.xml", "consolidated": "Consolidated",
                          "toDate": "31-Mar-2024"}]
            self.fail("should not fall back to insurance index when equities has data")

        with patch("src.fetch.historical_xbrl_backfill.nse_source.fetch_historical_financial_results",
                   side_effect=fake_fetch), \
             patch("src.fetch.historical_xbrl_backfill.pdf_downloader.download_filing",
                   return_value=True):
            downloaded = backfill_company("TCS")

        self.assertEqual(downloaded, 2)


if __name__ == "__main__":
    unittest.main()
