"""Neighbor context expansion (§17) on the shared retrieval fixture -- RELIANCE and TCS
each have 3 sequential chunks (index 0/1/2) in one document; INFY has a single chunk."""
from __future__ import annotations

import unittest

from finqa_v2.retrieval.context_expander import expand_with_neighbors
from finqa_v2.retrieval.retriever import HybridRetriever, RetrievedChunk
from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.sqlite import SqliteRepositories


class ExpandWithNeighbors(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)

    def _chunk_by_section(self, section: str):
        row = self.repos.connection.execute(
            "SELECT * FROM document_chunks WHERE section = ?", (section,)
        ).fetchone()
        from finqa_v2.sqlite.repo import _row_chunk
        return _row_chunk(row)

    def test_window_zero_is_a_no_op(self):
        ch = self._chunk_by_section("auditors_report")   # RELIANCE, chunk_index=1
        hits = [RetrievedChunk(chunk=ch, rank=1, scores={})]
        self.assertIs(expand_with_neighbors(hits, self.repos), hits)
        self.assertEqual(expand_with_neighbors(hits, self.repos, window=0), hits)

    def test_empty_hits_is_a_no_op(self):
        self.assertEqual(expand_with_neighbors([], self.repos, window=1), [])

    def test_window_one_pulls_in_both_neighbors(self):
        ch = self._chunk_by_section("auditors_report")   # RELIANCE, chunk_index=1
        hits = [RetrievedChunk(chunk=ch, rank=1, scores={"lexical": 1.0})]
        out = expand_with_neighbors(hits, self.repos, window=1)
        self.assertEqual(len(out), 3)
        sections = {h.chunk.section for h in out}
        self.assertEqual(sections, {"auditors_report", "segment_information", "cover_letter"})

    def test_neighbors_carry_the_anchors_rank_and_a_marker_score(self):
        ch = self._chunk_by_section("auditors_report")
        hits = [RetrievedChunk(chunk=ch, rank=3, scores={"lexical": 1.0})]
        out = expand_with_neighbors(hits, self.repos, window=1)
        neighbors = [h for h in out if h.chunk.section != "auditors_report"]
        self.assertEqual(len(neighbors), 2)
        for h in neighbors:
            self.assertEqual(h.rank, 3)
            self.assertEqual(h.scores, {"neighbor_of": ch.chunk_id})

    def test_edge_chunk_only_has_one_neighbor(self):
        ch = self._chunk_by_section("segment_information")   # RELIANCE, chunk_index=0 (first)
        # TCS also has a segment_information chunk -- disambiguate to RELIANCE's specifically
        row = self.repos.connection.execute(
            "SELECT dc.* FROM document_chunks dc JOIN companies c ON c.company_id = dc.company_id "
            "WHERE c.ticker = 'RELIANCE' AND dc.section = 'segment_information'"
        ).fetchone()
        from finqa_v2.sqlite.repo import _row_chunk
        ch = _row_chunk(row)
        hits = [RetrievedChunk(chunk=ch, rank=1, scores={})]
        out = expand_with_neighbors(hits, self.repos, window=1)
        self.assertEqual(len(out), 2)   # no chunk_index=-1 to pull in

    def test_single_chunk_document_has_no_neighbors(self):
        ch = self._chunk_by_section("cash_flow_statement")   # INFY's only chunk
        hits = [RetrievedChunk(chunk=ch, rank=1, scores={})]
        out = expand_with_neighbors(hits, self.repos, window=2)
        self.assertEqual(out, hits)

    def test_deduplicates_by_chunk_id_across_overlapping_anchors(self):
        # two adjacent anchors (index 0 and 1) both requesting window=1 would otherwise
        # both try to add index 1/0 to each other and index 2 twice -- confirm no dupes.
        rows = self.repos.connection.execute(
            "SELECT dc.* FROM document_chunks dc JOIN companies c ON c.company_id = dc.company_id "
            "WHERE c.ticker = 'TCS' ORDER BY dc.chunk_index"
        ).fetchall()
        from finqa_v2.sqlite.repo import _row_chunk
        chunks = [_row_chunk(r) for r in rows]
        hits = [RetrievedChunk(chunk=chunks[0], rank=1, scores={}),
                RetrievedChunk(chunk=chunks[1], rank=2, scores={})]
        out = expand_with_neighbors(hits, self.repos, window=1)
        ids = [h.chunk.chunk_id for h in out]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(out), 3)   # all 3 TCS chunks, no duplicates

    def test_a_neighbor_already_present_as_its_own_hit_is_not_duplicated(self):
        rows = self.repos.connection.execute(
            "SELECT dc.* FROM document_chunks dc JOIN companies c ON c.company_id = dc.company_id "
            "WHERE c.ticker = 'TCS' ORDER BY dc.chunk_index"
        ).fetchall()
        from finqa_v2.sqlite.repo import _row_chunk
        chunks = [_row_chunk(r) for r in rows]
        hits = [RetrievedChunk(chunk=chunks[0], rank=1, scores={"lexical": 2.0}),
                RetrievedChunk(chunk=chunks[1], rank=2, scores={"lexical": 1.0})]
        out = expand_with_neighbors(hits, self.repos, window=1)
        self.assertEqual(len(out), 3)
        # chunks[1] stays the original ranked hit, not overwritten by the neighbor copy
        kept = next(h for h in out if h.chunk.chunk_id == chunks[1].chunk_id)
        self.assertEqual(kept.scores, {"lexical": 1.0})


class RetrieverNeighborWindow(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        from finqa_v2.retrieval.lexical import BM25Index
        self.r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos))

    def test_neighbor_window_zero_is_unchanged_from_omitting_the_argument(self):
        query = "independent auditor report basis for opinion"
        with_default = self.r.retrieve(query, k=3, mode="lexical")
        explicit_zero = self.r.retrieve(query, k=3, mode="lexical", neighbor_window=0)
        self.assertEqual([h.chunk.chunk_id for h in with_default],
                         [h.chunk.chunk_id for h in explicit_zero])

    def test_neighbor_window_grows_the_result_past_k(self):
        query = "independent auditor report basis for opinion"
        base = self.r.retrieve(query, k=1, mode="lexical", rerank=False)
        self.assertEqual(len(base), 1)
        expanded = self.r.retrieve(query, k=1, mode="lexical", rerank=False, neighbor_window=1)
        self.assertGreater(len(expanded), 1)


if __name__ == "__main__":
    unittest.main()
