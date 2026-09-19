"""build_embedding_text / from_row -- the metadata header prepended before embedding."""
from __future__ import annotations

import unittest

from finqa_v2.retrieval.text_builder import build_embedding_text, from_row


class TestBuildEmbeddingText(unittest.TestCase):
    def test_no_metadata_returns_text_unchanged(self):
        self.assertEqual(build_embedding_text("hello"), "hello")

    def test_company_only(self):
        self.assertEqual(build_embedding_text("hello", company="TCS"), "TCS\n\nhello")

    def test_all_fields_in_order(self):
        out = build_embedding_text(
            "hello", company="TCS", financial_year=2026,
            document_type="results_pdf", section="financial_results", page=3,
        )
        self.assertEqual(out, "TCS | FY2026 | results pdf | financial results | page 3\n\nhello")

    def test_falsy_fields_omitted(self):
        out = build_embedding_text("hello", company="TCS", financial_year=None, page=0)
        self.assertEqual(out, "TCS\n\nhello")


class TestFromRow(unittest.TestCase):
    def test_pulls_fields_from_a_dict_like_row(self):
        row = {"text": "hello", "ticker": "TCS", "financial_year": 2026,
               "document_type": "results_pdf", "section": "financial_results",
               "page_start": 3}
        self.assertEqual(from_row(row),
                         "TCS | FY2026 | results pdf | financial results | page 3\n\nhello")

    def test_no_ticker_key_is_tolerated(self):
        row = {"text": "hello", "financial_year": 2026, "document_type": None,
               "section": None, "page_start": None}
        self.assertEqual(from_row(row), "FY2026\n\nhello")


if __name__ == "__main__":
    unittest.main()
