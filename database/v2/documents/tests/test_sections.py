"""Section detection over a fixture PDF."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database.v2.documents.extract import extract_pages
from database.v2.documents.sections import detect_sections
from database.v2.documents.tests._fixture_pdf import make_results_pdf


class TestSections(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.pdf = make_results_pdf(Path(cls.tmp.name) / "fixture.pdf")
        cls.res = extract_pages(cls.pdf)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_extract_ok_clean_text(self):
        self.assertTrue(self.res.ok)
        self.assertEqual(self.res.page_count, 3)
        joined = " ".join(p.text for p in self.res.pages)
        self.assertIn("Audited Financial Results", joined)
        self.assertNotIn("�", joined)          # no mojibake

    def test_span_labels(self):
        spans = detect_sections(self.res.pages)
        by_page = {}
        for s in spans:
            for pg in range(s.page_start, s.page_end + 1):
                by_page[pg] = s.section
        self.assertEqual(by_page[1], "cover_letter")
        self.assertEqual(by_page[2], "auditors_report")
        self.assertEqual(by_page[3], "segment_information")

    def test_spans_are_contiguous_and_cover_all_pages(self):
        spans = detect_sections(self.res.pages)
        covered = []
        for s in spans:
            self.assertLessEqual(s.page_start, s.page_end)
            covered.extend(range(s.page_start, s.page_end + 1))
        self.assertEqual(sorted(covered), [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
