"""Smoke test against a real results PDF, if the raw corpus is present."""
from __future__ import annotations

import unittest
from pathlib import Path

from finqa_v2.documents.extract import extract_pages
from finqa_v2.documents.pipeline import ingest_pdf
from finqa_v2.documents.sections import detect_sections
from finqa_v2.models import Company
from finqa_v2.sqlite import SqliteRepositories

_RAW = Path(__file__).resolve().parents[3] / "data_extraction" / "data" / "raw"


def _first_pdf():
    if not _RAW.exists():
        return None
    for sub in sorted(_RAW.iterdir()):
        pdfs = sorted(sub.glob("*.pdf"))
        if pdfs:
            return sub.name, pdfs[0]
    return None


@unittest.skipUnless(_first_pdf(), "no raw PDFs present")
class TestRealPdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.symbol, cls.pdf = _first_pdf()

    def test_extract_and_sections(self):
        res = extract_pages(self.pdf)
        self.assertTrue(res.ok, res.error)
        self.assertGreater(res.page_count, 3)
        self.assertNotIn("�", " ".join(p.text for p in res.pages[:5]))
        spans = detect_sections(res.pages)
        self.assertTrue(spans)
        covered = [pg for s in spans for pg in range(s.page_start, s.page_end + 1)]
        self.assertEqual(sorted(covered), list(range(1, res.page_count + 1)))
        # a results PDF should surface at least one recognisable section
        self.assertTrue({s.section for s in spans} & {
            "auditors_report", "financial_results", "cover_letter", "segment_information", "notes"})

    def test_ingest_into_memory(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        repos.companies.upsert(Company(name=self.symbol, ticker=self.symbol))
        r = ingest_pdf(self.pdf, repos, company=self.symbol)
        self.assertNotIn("skipped", r, r.get("skipped"))
        self.assertGreater(r["chunks"], 5)
        cid = repos.companies.get_by_ticker(self.symbol).company_id
        chunks = repos.documents.chunks_for(repos.documents.for_company(cid)[0].document_id)
        self.assertTrue(all(c.page_start and c.page_start <= c.page_end for c in chunks))
        self.assertTrue(all(c.char_count > 0 for c in chunks))


if __name__ == "__main__":
    unittest.main()
