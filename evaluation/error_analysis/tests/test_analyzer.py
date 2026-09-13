import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "retrieval_v21.json"


@unittest.skipUnless(DB.exists() and DATASET.exists(), "finqa_v2.db / retrieval_v21.json not built")
class Analyze(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.retrieval.evaluate import build_retriever
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.error_analysis.analyzer import analyze
        from evaluation.error_analysis.classifier import ERROR_CLASSES
        from evaluation.run_retrieval_benchmark import load_dataset

        cls.ERROR_CLASSES = ERROR_CLASSES
        cls.records = load_dataset(DATASET)
        cls.repos = SqliteRepositories(DB)
        cls.retriever = build_retriever(cls.repos, bm25_path=ROOT / "database" / "data" / "finqa_v2_bm25.pkl",
                                        vector_dir=ROOT / "database" / "data" / "finqa_v2_vec")
        # computed once and shared -- analyze() re-runs retrieval per case, so this is the
        # slow part; every test below only reads these two already-computed reports.
        cls.lexical_report = analyze(cls.retriever, cls.repos, cls.records, mode="lexical", k=5)
        cls.hybrid_report = analyze(cls.retriever, cls.repos, cls.records, mode="hybrid", k=5)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_only_non_adversarial_cases_are_scored(self):
        n_gold_bearing = sum(1 for r in self.records if r["gold_chunks"])
        self.assertEqual(self.lexical_report["n_scored"], n_gold_bearing)

    def test_distribution_sums_to_failure_count(self):
        total = sum(d["count"] for d in self.lexical_report["distribution"].values())
        self.assertEqual(total, self.lexical_report["n_failures"])

    def test_every_reported_class_is_a_known_error_class(self):
        for case in self.lexical_report["per_case"]:
            self.assertIn(case["error_class"], self.ERROR_CLASSES)

    def test_missing_document_never_appears_in_this_benchmark(self):
        self.assertEqual(self.hybrid_report["distribution"]["MISSING_DOCUMENT"]["count"], 0)

    def test_failure_rate_is_between_zero_and_one(self):
        self.assertGreaterEqual(self.hybrid_report["failure_rate"], 0.0)
        self.assertLessEqual(self.hybrid_report["failure_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
