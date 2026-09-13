import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "retrieval_v21.json"


@unittest.skipUnless(DB.exists() and DATASET.exists(), "finqa_v2.db / retrieval_v21.json not built")
class BenchmarkModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.run_retrieval_benchmark import load_dataset

        cls.records = load_dataset(DATASET)[:20]  # a slice keeps this test fast
        cls.repos = SqliteRepositories(DB)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_missing_vector_dir_is_reported_as_skipped_not_an_error(self):
        from evaluation.benchmarks.embeddings import benchmark_model

        result = benchmark_model("fake-model", ROOT / "does" / "not" / "exist", self.repos, self.records)
        self.assertIn("skipped", result)

    def test_current_shipped_index_produces_the_full_metric_shape(self):
        from evaluation.benchmarks.embeddings import CANDIDATES, benchmark_model

        current_dir = CANDIDATES["all-MiniLM-L6-v2 (current)"]
        if not current_dir.exists():
            self.skipTest("finqa_v2_vec (MiniLM) index not built")
        result = benchmark_model("all-MiniLM-L6-v2 (current)", current_dir, self.repos, self.records)
        self.assertNotIn("skipped", result)
        for key in ("index_size_mb", "embed_latency_ms_per_chunk", "query_p50_ms",
                    "recall@5", "recall@10", "mrr", "ndcg@5"):
            self.assertIn(key, result)
            self.assertIsNotNone(result[key])


if __name__ == "__main__":
    unittest.main()
