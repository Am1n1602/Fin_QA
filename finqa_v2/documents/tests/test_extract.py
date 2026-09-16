"""`_strip_table_boilerplate` (§15/Phase 20-follow-up): PyMuPDF's find_tables() sweeps a
results-PDF page's letterhead into the same bounding box as the real data table below it
-- confirmed by direct inspection of real ingested chunks. These tests exercise the pure
string-filtering function directly (no PyMuPDF dependency needed); `test_real_pdf.py`
covers the full extraction pipeline against an actual PDF.
"""
import unittest

from finqa_v2.documents.extract import _strip_table_boilerplate


class StripTableBoilerplate(unittest.TestCase):
    def test_drops_a_cin_line(self):
        rendered = "Bajaj Finserv Limited\tCIN : L65923PN2007PLC130075\nIncome\t190.42\t226.02"
        self.assertEqual(_strip_table_boilerplate(rendered), "Income\t190.42\t226.02")

    def test_drops_registered_and_corporate_office_lines(self):
        rendered = (
            "Registered Office: C/o Bajaj Auto Limited Complex\n"
            "Corporate Office: 6th Floor, Bajaj Finserv Corporate Office\n"
            "Particulars\tQuarter ended\tYear ended"
        )
        self.assertEqual(_strip_table_boilerplate(rendered), "Particulars\tQuarter ended\tYear ended")

    def test_drops_website_email_telephone_and_fax_lines(self):
        rendered = (
            "Website: www.aboutbajajfinserv.com/about-us\n"
            "E-mail ID : investors@bajajfinserv.in\n"
            "Telephone : +91 20 7150 5700\n"
            "Fax : +91 20 7150 5792\n"
            "Total income\t1200.5"
        )
        self.assertEqual(_strip_table_boilerplate(rendered), "Total income\t1200.5")

    def test_case_insensitive_and_matches_anywhere_in_the_line(self):
        rendered = "some prefix cin : ABC123 some suffix\nRevenue from operations\t500"
        self.assertEqual(_strip_table_boilerplate(rendered), "Revenue from operations\t500")

    def test_real_financial_data_lines_are_never_touched(self):
        rendered = (
            "Particulars\tQuarter ended\tYear ended\n"
            "Income\tInterest income\tDividend income\n"
            "Revenue from operations\t267021\t250000\n"
            "Profit for the period\t48553\t45000"
        )
        self.assertEqual(_strip_table_boilerplate(rendered), rendered)

    def test_empty_input_returns_empty(self):
        self.assertEqual(_strip_table_boilerplate(""), "")

    def test_all_boilerplate_leaves_an_empty_result(self):
        rendered = "CIN : L65923PN2007PLC130075\nRegistered Office: Somewhere"
        self.assertEqual(_strip_table_boilerplate(rendered), "")

    def test_realistic_mixed_letterhead_and_table_survives_with_only_boilerplate_removed(self):
        rendered = (
            "Bajaj Finserv Limited\n"
            "CIN : L65923PN2007PLC130075\n"
            "Registered Office: C/o Bajaj Auto Limited Complex, Pune\n"
            "Website: www.aboutbajajfinserv.com/about-us; E-mail ID : investors@bajajfinserv.in\n"
            "Telephone : +91 20 7150 5700\n"
            "Statement of unaudited financial results for the quarter ended 31 March 2026\n"
            "Particulars\tQuarter ended\tYear ended\n"
            "Interest income\t41.33\t190.42"
        )
        result = _strip_table_boilerplate(rendered)
        self.assertNotIn("CIN", result)
        self.assertNotIn("Registered Office", result)
        self.assertNotIn("Website", result)
        self.assertNotIn("Telephone", result)
        self.assertIn("Statement of unaudited financial results", result)
        self.assertIn("Interest income\t41.33\t190.42", result)
        # the plain company-name line has no boilerplate marker -- survives too, harmlessly
        self.assertIn("Bajaj Finserv Limited", result)


if __name__ == "__main__":
    unittest.main()
