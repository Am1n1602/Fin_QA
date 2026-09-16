"""Structure-aware chunking on synthetic pages/sections (no PDF needed)."""
from __future__ import annotations

import unittest

from finqa_v2.documents.chunk import _split_table, chunk_document
from finqa_v2.documents.extract import PageText
from finqa_v2.documents.sections import SectionSpan

_LONG = ("Paragraph number {n}. " * 30).strip()

PAGES = [
    PageText(1, "\n\n".join(f"P1 {_LONG.format(n=i)}" for i in range(4)),
             tables=["Metric\tFY25\tFY26\nRevenue\t1000\t1200"]),
    PageText(2, "\n\n".join(f"P2 {_LONG.format(n=i)}" for i in range(4))),
    PageText(3, "The Group operates in Retail and Digital Services segments. "
                "Retail revenue rose. " + _LONG.format(n=99)),
]
SECTIONS = [
    SectionSpan("cover_letter", None, 1, 2),
    SectionSpan("segment_information", None, 3, 3),
]


class TestChunkDocument(unittest.TestCase):
    def _chunks(self, **kw):
        return chunk_document(
            PAGES, SECTIONS, document_id=7, company_id=3,
            financial_year=2026, document_type="results_pdf",
            segment_slugs=("retail", "digital_services"), **kw,
        )

    def test_metadata_complete(self):
        for c in self._chunks():
            self.assertEqual(c.document_id, 7)
            self.assertEqual(c.company_id, 3)
            self.assertEqual(c.financial_year, 2026)
            self.assertEqual(c.document_type, "results_pdf")
            self.assertIsNotNone(c.section)
            self.assertGreater(c.char_count, 0)
            self.assertLessEqual(c.page_start, c.page_end)
        idxs = [c.chunk_index for c in self._chunks()]
        self.assertEqual(idxs, list(range(len(idxs))))          # 0..n-1, no gaps

    def test_table_is_its_own_chunk(self):
        chunks = self._chunks()
        tables = [c for c in chunks if c.topic == "table"]
        self.assertEqual(len(tables), 1)
        self.assertIn("Revenue\t1000\t1200", tables[0].text)
        self.assertEqual(tables[0].page_start, 1)
        # a prose chunk never contains the raw table row
        for c in chunks:
            if c.topic != "table":
                self.assertNotIn("Revenue\t1000\t1200", c.text)

    def test_prose_packed_near_target_and_page_ranges(self):
        prose = [c for c in self._chunks(target=900) if c.topic == "prose"]
        self.assertTrue(prose)
        # cover_letter prose spans pages 1-2
        cover = [c for c in prose if c.section == "cover_letter"]
        self.assertTrue(any(c.page_start == 1 for c in cover))
        self.assertTrue(any(c.page_end == 2 for c in cover))

    def test_segment_section_topic_and_slug(self):
        seg = [c for c in self._chunks() if c.section == "segment_information"]
        self.assertTrue(seg)
        self.assertTrue(all(c.topic in ("segment", "table") for c in seg))
        self.assertTrue(any(c.segment == "retail" for c in seg))

    def test_overlap_present(self):
        prose = [c for c in self._chunks(target=700, overlap=150) if c.topic == "prose"
                 and c.section == "cover_letter"]
        if len(prose) >= 2:
            tail = prose[0].text[-120:]
            self.assertTrue(any(w in prose[1].text for w in tail.split()[:5]))

    def test_a_large_table_splits_into_multiple_chunks(self):
        header = "|Particulars||Quarterended||Yearended|\n|---|---|---|---|---|\n||31.03.2026|31.12.2025|31.03.2025|31.03.2026|\n||(Unaudited)|(Unaudited)|(Unaudited)|(Audited)|"
        rows = "\n".join(f"|Line item {i}|{i*10}|{i*11}|{i*12}|{i*13}|" for i in range(40))
        big_table = header + "\n" + rows
        pages = [PageText(1, "prose text here", tables=[big_table])]
        sections = [SectionSpan("financial_results", None, 1, 1)]
        chunks = chunk_document(pages, sections, document_id=7, company_id=3,
                                financial_year=2026, document_type="results_pdf")
        tables = [c for c in chunks if c.topic == "table"]
        self.assertGreater(len(tables), 1, "a table this large should split into more than one chunk")
        # every split piece still carries the header so it stays interpretable alone
        for t in tables:
            self.assertIn("Particulars", t.text)
            self.assertIn("Quarterended", t.text)
        # every original data row survives somewhere across the split pieces
        combined = "\n".join(t.text for t in tables)
        for i in range(40):
            self.assertIn(f"Line item {i}", combined)

    def test_a_small_table_never_splits(self):
        small_table = "Metric\tFY25\tFY26\nRevenue\t1000\t1200\nProfit\t200\t250"
        pages = [PageText(1, "prose", tables=[small_table])]
        sections = [SectionSpan("financial_results", None, 1, 1)]
        chunks = chunk_document(pages, sections, document_id=7, company_id=3,
                                financial_year=2026, document_type="results_pdf")
        tables = [c for c in chunks if c.topic == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].text, small_table)


class SplitTable(unittest.TestCase):
    def test_a_table_at_or_under_target_is_returned_whole(self):
        small = "a" * 500
        self.assertEqual(_split_table(small, target=500), [small])

    def test_a_table_over_target_splits(self):
        header = "H1\nH2\nH3\nH4"
        rows = "\n".join(f"row{i} " + "x" * 50 for i in range(20))
        table = header + "\n" + rows
        pieces = _split_table(table, target=200, header_lines=4)
        self.assertGreater(len(pieces), 1)

    def test_every_piece_repeats_the_header_lines(self):
        header = "H1\nH2\nH3\nH4"
        rows = "\n".join(f"row{i} " + "x" * 50 for i in range(20))
        table = header + "\n" + rows
        pieces = _split_table(table, target=200, header_lines=4)
        for p in pieces:
            self.assertTrue(p.startswith("H1\nH2\nH3\nH4"))

    def test_no_data_is_lost_across_the_split(self):
        header = "H1\nH2\nH3\nH4"
        rows = [f"unique_row_marker_{i}" for i in range(20)]
        table = header + "\n" + "\n".join(rows)
        pieces = _split_table(table, target=100, header_lines=4)
        combined = "\n".join(pieces)
        for r in rows:
            self.assertIn(r, combined)

    def test_too_few_lines_to_split_returns_whole(self):
        table = "H1\nH2\nH3\nH4\none data row " + "x" * 1000
        pieces = _split_table(table, target=50, header_lines=4)
        self.assertEqual(pieces, [table])

    def test_a_table_with_no_newlines_returns_whole(self):
        table = "x" * 1000  # no \n at all -- nothing to split on
        pieces = _split_table(table, target=500)
        self.assertEqual(pieces, [table])


if __name__ == "__main__":
    unittest.main()
