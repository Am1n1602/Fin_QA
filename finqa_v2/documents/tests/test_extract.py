"""`_strip_table_boilerplate` (§15/Phase 20-follow-up): PyMuPDF's find_tables() sweeps a
results-PDF page's letterhead into the same bounding box as the real data table below it
-- confirmed by direct inspection of real ingested chunks. These tests exercise the pure
string-filtering function directly (no PyMuPDF dependency needed); `test_real_pdf.py`
covers the full extraction pipeline against an actual PDF.
"""
import unittest

from finqa_v2.documents.extract import _group_logical_rows, _strip_table_boilerplate


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


class GroupLogicalRows(unittest.TestCase):
    """Re-assembles raw PyMuPDF `get_text('text', clip=...)` output -- one label or
    value per line -- into logical (label, value, value, ...) rows, tab-joined to match
    the row-per-line shape chunk.py's table splitter expects. Fixes a real
    pymupdf_layout bug (its own markdown cell assembly drops spaces between words --
    "Total revenue from operations" -> "Totalrevenuefromoperations" -- confirmed by
    direct comparison against this same raw PyMuPDF text, which has always been
    correct)."""

    def test_a_label_absorbs_its_following_numeric_values(self):
        lines = ["Interest income", "41.33", "54.05", "57.58", "190.42", "226.02"]
        groups = _group_logical_rows(lines)
        self.assertEqual(groups, [["Interest income", "41.33", "54.05", "57.58", "190.42", "226.02"]])

    def test_a_new_label_starts_a_new_group(self):
        lines = ["Interest income", "41.33", "54.05", "Dividend income", "1,788.45", "2,001.58"]
        groups = _group_logical_rows(lines)
        self.assertEqual(groups, [
            ["Interest income", "41.33", "54.05"],
            ["Dividend income", "1,788.45", "2,001.58"],
        ])

    def test_dates_and_audited_tags_count_as_values_not_labels(self):
        lines = ["Year ended", "31.03.2026", "31.03.2025", "(Unaudited)", "(Audited)", "Income"]
        groups = _group_logical_rows(lines)
        self.assertEqual(groups, [
            ["Year ended", "31.03.2026", "31.03.2025", "(Unaudited)", "(Audited)"],
            ["Income"],
        ])

    def test_a_lone_period_or_dash_placeholder_counts_as_a_value(self):
        lines = ["Dividend income", ".", ".", "1,788.45", "2,001.58"]
        groups = _group_logical_rows(lines)
        self.assertEqual(groups, [["Dividend income", ".", ".", "1,788.45", "2,001.58"]])

    def test_negative_parenthesized_amounts_count_as_values(self):
        lines = ["Deferred tax", "(3.09)", "1.71", "(0.14)"]
        groups = _group_logical_rows(lines)
        self.assertEqual(groups, [["Deferred tax", "(3.09)", "1.71", "(0.14)"]])

    def test_empty_input_returns_no_groups(self):
        self.assertEqual(_group_logical_rows([]), [])

    def test_the_real_bajajfinsv_table_groups_cleanly(self):
        lines = [
            "Particulars", "Quarter ended", "Year ended",
            "31.03.2026", "31.12.2025", "31.03.2025", "31.03.2026", "31.03.2025",
            "(Unaudited)", "(Unaudited)", "(Unaudited)", "(Audited)", "(Audited)", "1",
            "Income",
            "Interest income", "41.33", "54.05", "57.58", "190.42", "226.02",
            "Total revenue from operations", "46.73", "62.62", "64.64", "2,016.23", "2,261.68",
        ]
        groups = _group_logical_rows(lines)
        labels = [g[0] for g in groups]
        self.assertIn("Total revenue from operations", labels)
        revenue_row = next(g for g in groups if g[0] == "Total revenue from operations")
        self.assertEqual(revenue_row, ["Total revenue from operations", "46.73", "62.62", "64.64",
                                       "2,016.23", "2,261.68"])
        # the tab-joined form chunk.py's splitter consumes never re-merges label+values
        # back into a single word -- "Total revenue from operations" stays intact
        rendered = "\n".join("\t".join(g) for g in groups)
        self.assertIn("Total revenue from operations\t46.73", rendered)


if __name__ == "__main__":
    unittest.main()
