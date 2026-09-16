"""Scale harness: footprint measurement, projection math, BM25 filter-before-scoring."""
from __future__ import annotations

import unittest

import finqa_v2.scale.measure as _measure
import finqa_v2.scale.project as _project
from finqa_v2.retrieval import BM25Index
from finqa_v2.retrieval.tests._fixture import seed as seed_docs
from finqa_v2.sqlite import SqliteRepositories


class TestMeasure(unittest.TestCase):
    def test_footprint_shape(self):
        repos = SqliteRepositories(":memory:")
        self.addCleanup(repos.close)
        ids = seed_docs(repos)
        fp = _measure.measure_footprint(repos)
        self.assertEqual(fp["companies"], len(ids))
        self.assertEqual(fp["counts"]["document_chunks"], 7)
        self.assertIn("db_bytes", fp["storage_bytes"])
        self.assertIn("chunks", fp["per_company"])
        self.assertGreater(fp["per_company"]["chunks"], 0)
        _measure.render(fp)                       # must not raise


class TestProject(unittest.TestCase):
    def _fp(self):
        return {
            "companies": 50, "index_members": 50, "counts": {},
            "storage_bytes": {},
            "per_company": {
                "facts": 500.0, "segment_facts": 50.0, "share_prices": 250.0,
                "documents": 12.0, "chunks": 640.0, "sources": 30.0,
                "db_bytes": 2_000_000.0, "bm25_index_bytes": 1_100_000.0,
                "vector_index_bytes": 2_000_000.0,
            },
        }

    def test_linear_scaling(self):
        p = _project.project(self._fp(), benchmark=None, targets=(100, 500))
        rows = {r["companies"]: r for r in p["rows"]}
        self.assertEqual(rows[100]["facts"], 50_000)          # 500 * 100
        self.assertEqual(rows[500]["chunks"], 320_000)        # 640 * 500
        self.assertAlmostEqual(rows[500]["db_gb"], 1.0, places=2)
        self.assertEqual(rows[500]["scale_x"], 10.0)

    def test_latency_is_flat(self):
        bench = {"pipeline_overall": {"p50_of_p50_ms": 2.0}}
        p = _project.project(self._fp(), bench, targets=(500,))
        self.assertEqual(p["rows"][-1]["pipeline_p50_ms_est"], 2.0)   # same as base

    def test_bm25_threshold_crosses_at_500(self):
        # 1.1 MB/co * 500 = 550 MB > 1500? no. bump per-co to force it.
        fp = self._fp()
        fp["per_company"]["bm25_index_bytes"] = 4_000_000.0          # 4 MB/co -> 2 GB @ 500
        p = _project.project(fp, None, targets=(500,))
        crossed = {c["metric"] for c in p["thresholds_crossed_at_max"]}
        self.assertIn("bm25_ram_mb", crossed)
        self.assertIn("Postgres", p["verdict"])
        _project.render(p)

    def test_no_threshold_verdict(self):
        p = _project.project(self._fp(), None, targets=(500,))
        self.assertEqual(p["thresholds_crossed_at_max"], [])
        self.assertIn("holds to 500", p["verdict"])


class TestBM25FilterBeforeScoring(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        self.ids = seed_docs(self.repos)
        self.bm25 = BM25Index.build(self.repos)

    def test_company_filter_restricts_via_index(self):
        tcs = self.ids["TCS"]
        kept = self.bm25._kept_positions({"company_id": tcs})
        self.assertIsNotNone(kept)
        self.assertEqual(len(kept), 3)                        # TCS has 3 chunks
        for pos in kept:
            self.assertEqual(self.bm25.meta[pos]["company_id"], tcs)

    def test_search_with_filter_returns_only_that_company(self):
        tcs = self.ids["TCS"]
        hits = self.bm25.search("segment revenue banking board", k=10,
                                filters={"company_id": tcs})
        self.assertTrue(hits)
        tcs_chunk_ids = {p for p, m in enumerate(self.bm25.meta)}  # positions
        for h in hits:
            pos = self.bm25.chunk_ids.index(h.chunk_id)
            self.assertEqual(self.bm25.meta[pos]["company_id"], tcs)

    def test_multi_key_filter_intersects(self):
        tcs = self.ids["TCS"]
        kept = self.bm25._kept_positions({"company_id": tcs, "section": "segment_information"})
        self.assertEqual(len(kept), 1)

    def test_unindexed_filter_key_falls_back(self):
        # 'topic' is not in _INDEXED_KEYS -> _kept_positions returns None, search still works
        self.assertIsNone(self.bm25._kept_positions({"topic": "segment"}))
        hits = self.bm25.search("segment revenue", k=10, filters={"topic": "segment"})
        self.assertTrue(all(
            self.bm25.meta[self.bm25.chunk_ids.index(h.chunk_id)]["topic"] == "segment"
            for h in hits))


if __name__ == "__main__":
    unittest.main()
