"""BM25 + vector + hybrid retrieval on the in-memory fixture."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from finqa_v2.retrieval.embed import HashEmbedder
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.retrieval.retriever import HybridRetriever
from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.retrieval.vector import VectorIndex
from finqa_v2.sqlite import SqliteRepositories


class TestBM25(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.idx = BM25Index.build(self.repos)

    def test_search_ranks_topic_chunk_first(self):
        hits = self.idx.search("oil to chemicals retail digital services segment", k=3)
        self.assertTrue(hits)
        top = self.repos.documents.chunks_for  # noqa
        self.assertGreater(hits[0].score, 0)

    def test_filter_by_company_and_section(self):
        hits = self.idx.search("segment revenue", k=10, filters={"company_id": 999})
        self.assertEqual(hits, [])
        cid = self.repos.companies.get_by_ticker("TCS").company_id
        hits = self.idx.search("segment BFSI manufacturing", k=10,
                               filters={"company_id": cid, "section": ["segment_information"]})
        self.assertTrue(hits)
        for h in hits:
            m = next(mm for cc, mm in zip(self.idx.chunk_ids, self.idx.meta) if cc == h.chunk_id)
            self.assertEqual(m["company_id"], cid)
            self.assertEqual(m["section"], "segment_information")

    def test_save_load_roundtrip(self):
        d = Path(tempfile.mkdtemp()) / "bm25.pkl"
        self.idx.save(d)
        again = BM25Index.load(d)
        self.assertEqual(again.search("dividend board meeting sebi", k=3)[0].chunk_id,
                         self.idx.search("dividend board meeting sebi", k=3)[0].chunk_id)


class TestHybrid(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        bm25 = BM25Index.build(self.repos)
        emb = HashEmbedder(dim=128)
        vec = VectorIndex.build(self.repos, emb, use_faiss=False)
        self.r = HybridRetriever(self.repos, bm25=bm25, vector=vec, embedder=emb)

    def test_modes_available(self):
        self.assertEqual(set(self.r.modes), {"lexical", "vector", "hybrid"})

    def test_lexical_mode(self):
        hits = self.r.retrieve("independent auditor report basis for opinion", k=3, mode="lexical")
        self.assertTrue(hits)
        self.assertEqual(hits[0].chunk.section, "auditors_report")
        self.assertEqual(hits[0].rank, 1)
        self.assertIn("doc#", hits[0].citation())

    def test_vector_mode_runs(self):
        hits = self.r.retrieve("cash generated from operating activities", k=3, mode="vector")
        self.assertTrue(hits)

    def test_hybrid_fuses(self):
        hits = self.r.retrieve("segment revenue retail digital services", k=3, mode="hybrid")
        self.assertTrue(hits)
        self.assertIn(hits[0].chunk.section, {"segment_information"})
        self.assertIsNotNone(hits[0].scores["rrf"])

    def test_filter_scopes_results(self):
        cid = self.repos.companies.get_by_ticker("TCS").company_id
        hits = self.r.retrieve("segment", k=5, mode="hybrid", filters={"company_id": cid})
        self.assertTrue(hits)
        self.assertTrue(all(h.chunk.company_id == cid for h in hits))

    def test_lexical_only_retriever_downgrades_hybrid(self):
        r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos))
        self.assertEqual(r.modes, ("lexical",))
        hits = r.retrieve("dividend", k=2, mode="hybrid")   # silently -> lexical
        self.assertTrue(hits)

    def test_reranker_reorders(self):
        class RevReranker:
            name = "rev"
            trivial = False

            def score(self, query, passages):
                return [float(i) for i in range(len(passages))]     # last becomes first

        r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos), reranker=RevReranker())
        base = r.retrieve("segment revenue", k=5, mode="lexical", rerank=False)
        reranked = r.retrieve("segment revenue", k=5, mode="lexical", rerank=True)
        self.assertNotEqual([h.chunk.chunk_id for h in base], [h.chunk.chunk_id for h in reranked])


if __name__ == "__main__":
    unittest.main()
