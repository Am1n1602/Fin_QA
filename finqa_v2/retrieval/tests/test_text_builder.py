import unittest

from finqa_v2.retrieval.text_builder import build_embedding_text


class BuildEmbeddingText(unittest.TestCase):
    def test_no_metadata_returns_text_unchanged(self):
        self.assertEqual(build_embedding_text(text="Operating margin declined by 2.1%."),
                         "Operating margin declined by 2.1%.")

    def test_full_metadata_header(self):
        out = build_embedding_text(
            text="Operating margin declined by 2.1%.", company_name="TCS",
            financial_year=2026, document_type="annual_report", section="mda", page_start=72,
        )
        self.assertEqual(out, (
            "Company: TCS\n"
            "Period: FY2026\n"
            "Document: annual_report\n"
            "Section: mda\n"
            "Page: 72\n"
            "\n"
            "Operating margin declined by 2.1%."
        ))

    def test_partial_metadata_only_includes_whats_given(self):
        out = build_embedding_text(text="Revenue grew.", company_name="TCS", section="mda")
        self.assertEqual(out, "Company: TCS\nSection: mda\n\nRevenue grew.")

    def test_falsy_fields_are_omitted_not_rendered_as_empty_lines(self):
        out = build_embedding_text(text="X", company_name="", financial_year=0, page_start=0)
        self.assertEqual(out, "X")


if __name__ == "__main__":
    unittest.main()
