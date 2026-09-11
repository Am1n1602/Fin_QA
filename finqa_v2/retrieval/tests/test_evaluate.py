"""Retrieval eval harness math, and a lexical run against the real finqa_v2.db if present."""
from __future__ import annotations

import unittest
from pathlib import Path

from finqa_v2.retrieval.evaluate import build_retriever, evaluate, load_cases
from finqa_v2.retrieval.lexical import BM25Index
from finqa_v2.retrieval.rerank import CrossEncoderReranker, IdentityReranker
from finqa_v2.retrieval.retriever import HybridRetriever
from finqa_v2.retrieval.tests._fixture import seed
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories


class TestBuildRetrieverReranker(unittest.TestCase):
    """`use_reranker` construction only -- never calls `.score()`, so no network/model
    load happens in this fast unit test (CrossEncoderReranker's model is lazy)."""

    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)

    def test_default_is_no_reranker(self):
        r = build_retriever(self.repos, bm25_path=Path("/nonexistent"), vector_dir=Path("/nonexistent"))
        self.assertIsInstance(r._reranker, IdentityReranker)

    def test_use_reranker_true_wires_a_real_cross_encoder(self):
        r = build_retriever(self.repos, bm25_path=Path("/nonexistent"), vector_dir=Path("/nonexistent"),
                            use_reranker=True)
        self.assertIsInstance(r._reranker, CrossEncoderReranker)
        self.assertIsNone(r._reranker._model)  # constructed, not loaded


class TestEvaluateMath(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.r = HybridRetriever(self.repos, bm25=BM25Index.build(self.repos))

    def test_recall_and_mrr(self):
        cases = [
            {"id": "a", "query": "independent auditor report basis for opinion",
             "company": "RELIANCE", "sections": ["auditors_report"], "must_contain": ["opinion"]},
            {"id": "b", "query": "banking financial services insurance manufacturing segment",
             "company": "TCS", "sections": ["segment_information"], "must_contain": ["segment"]},
            {"id": "c", "query": "text that matches nothing zzzqqq",
             "company": "INFY", "sections": ["mda"], "must_contain": ["nonexistent"]},
        ]
        rep = evaluate(self.r, self.repos, cases, modes=("lexical",))["lexical"]
        self.assertEqual(rep["n"], 3)
        self.assertGreaterEqual(rep["recall@5"], 2 / 3)      # a and b should hit
        self.assertLessEqual(rep["recall@5"], 1.0)
        self.assertGreater(rep["mrr"], 0)
        self.assertIsNotNone(rep["p50_ms"])
        self.assertEqual(len(rep["per_case"]), 3)


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "finqa_v2.db not built")
class TestRealCorpus(unittest.TestCase):
    def test_lexical_baseline_over_shipped_cases(self):
        repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        self.addCleanup(repos.close)
        if repos.connection.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0] == 0:
            self.skipTest("no document_chunks in db")
        from pathlib import Path
        cases = load_cases(Path(__file__).resolve().parents[1] / "eval_cases.jsonl")
        r = build_retriever(repos, bm25_path=Path("/nonexistent"), vector_dir=Path("/nonexistent"))
        rep = evaluate(r, repos, cases, modes=("lexical",))["lexical"]
        # a lexical baseline over keyword-heavy cases should clear a low bar
        self.assertGreaterEqual(rep["recall@5"], 0.5, rep)
        self.assertGreater(rep["mrr"], 0.3, rep)


if __name__ == "__main__":
    unittest.main()
