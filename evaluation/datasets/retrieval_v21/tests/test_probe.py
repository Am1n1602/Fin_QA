import sqlite3
import unittest

from evaluation.datasets.retrieval_v21.probe import distinct_document_types, probe


def _fixture_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE document_chunks (chunk_id INTEGER PRIMARY KEY, company_id INTEGER, "
        "document_id INTEGER, text TEXT, section TEXT, document_type TEXT, topic TEXT, "
        "financial_year INTEGER)"
    )
    rows = [
        (1, 10, 100, "Revenue from operations grew due to higher volumes.", "mda", "annual_report", "prose", 2026),
        (2, 10, 101, "Segment: Retail. Revenue was strong.", "segment_information", "annual_report", "segment", 2026),
        (3, 10, 102, "Revenue from operations grew due to higher volumes.", "mda", "transcript", "prose", 2026),
        (4, 20, 103, "Total income for the quarter was steady.", "financial_results", "results_pdf", "table", 2027),
        (5, 10, 104, "100% discount voucher offer.", "risk_factors", "annual_report", "prose", None),
        (6, 30, 105, "Net profit margin improved this year.", "mda", "annual_report", "prose", 2024),
        (7, 30, 106, "Net profit margin improved this year.", "mda", "annual_report", "prose", 2026),
        (8, 30, 107, "Net profit margin improved this year.", "mda", "annual_report", "prose", None),
        (9, 30, 108, "Net profit margin improved this year.", "mda", "annual_report", "prose", 2025),
    ]
    conn.executemany(
        "INSERT INTO document_chunks VALUES (?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    return conn


class Probe(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture_conn()

    def test_keyword_and_company_filter(self):
        hits = probe(self.conn, company_id=10, keyword="revenue from operations")
        self.assertEqual({h.chunk_id for h in hits}, {1, 3})

    def test_section_filter(self):
        hits = probe(self.conn, company_id=10, sections=["segment_information"])
        self.assertEqual({h.chunk_id for h in hits}, {2})

    def test_financial_year_filter_excludes_absent_year(self):
        hits = probe(self.conn, company_id=10, financial_year=2015, keyword="revenue")
        self.assertEqual(hits, [])

    def test_no_filters_returns_up_to_limit(self):
        hits = probe(self.conn, limit=2)
        self.assertEqual(len(hits), 2)

    def test_keyword_wildcard_characters_are_escaped_not_interpreted(self):
        # a literal '%' in the keyword must not act as a SQL wildcard
        hits = probe(self.conn, company_id=10, keyword="100% discount")
        self.assertEqual({h.chunk_id for h in hits}, {5})
        # a bare '%' must only match chunks with a literal '%' character, not every row
        hits_wild = probe(self.conn, company_id=20, keyword="%")
        self.assertEqual(hits_wild, [])

    def test_default_ordering_is_ascending_by_chunk_id(self):
        hits = probe(self.conn, company_id=30, keyword="net profit margin", limit=3)
        self.assertEqual([h.chunk_id for h in hits], [6, 7, 8])

    def test_prefer_recent_orders_by_financial_year_desc_with_nulls_last(self):
        hits = probe(self.conn, company_id=30, keyword="net profit margin", limit=3, prefer_recent=True)
        # fy=2026 (chunk 7) first, then fy=2025 (chunk 9), then fy=2024 (chunk 6) --
        # fy=None (chunk 8) excluded entirely since limit=3 only takes the top 3.
        self.assertEqual([h.chunk_id for h in hits], [7, 9, 6])

    def test_prefer_recent_puts_null_financial_year_last_not_first(self):
        hits = probe(self.conn, company_id=30, keyword="net profit margin", limit=4, prefer_recent=True)
        self.assertEqual([h.chunk_id for h in hits], [7, 9, 6, 8])

    def test_distinct_document_types(self):
        types = distinct_document_types(self.conn, company_id=10, keyword="revenue from operations")
        self.assertEqual(set(types), {"annual_report", "transcript"})

    def test_distinct_document_types_empty_when_no_match(self):
        types = distinct_document_types(self.conn, company_id=20, keyword="nonexistent phrase")
        self.assertEqual(types, [])


if __name__ == "__main__":
    unittest.main()
