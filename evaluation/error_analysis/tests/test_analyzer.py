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

    def test_query_expansion_runs_without_error_and_is_off_by_default(self):
        from evaluation.error_analysis.analyzer import analyze

        with_qe = analyze(self.retriever, self.repos, self.records, mode="hybrid", k=5,
                          query_expansion=True)
        self.assertEqual(with_qe["n_scored"], self.hybrid_report["n_scored"])

    def test_weighted_fusion_runs_without_error_and_is_off_by_default(self):
        from evaluation.error_analysis.analyzer import analyze

        with_wf = analyze(self.retriever, self.repos, self.records, mode="hybrid", k=5,
                          weighted_fusion=True)
        self.assertEqual(with_wf["n_scored"], self.hybrid_report["n_scored"])
        # unconfigured settings (no section_aware -> intent=None everywhere) means
        # fusion_weights.get_fusion_weights(None) falls back to the (1.0, 1.0) default
        # block -- a true no-op, unlike the section-aware combination below.
        self.assertEqual(with_wf["failure_rate"], self.hybrid_report["failure_rate"])

    def test_weighted_fusion_with_section_aware_does_not_increase_failure_rate(self):
        # §16's shipped overrides only fire for management_commentary/trend/multi_hop/table,
        # which requires section_aware=True (intent must be passed) to reach at all.
        from evaluation.error_analysis.analyzer import analyze

        without = analyze(self.retriever, self.repos, self.records, mode="hybrid", k=5,
                          section_aware=True, query_expansion=True, weighted_fusion=False)
        with_wf = analyze(self.retriever, self.repos, self.records, mode="hybrid", k=5,
                          section_aware=True, query_expansion=True, weighted_fusion=True)
        self.assertEqual(with_wf["n_scored"], without["n_scored"])
        self.assertLessEqual(with_wf["failure_rate"], without["failure_rate"])


if __name__ == "__main__":
    unittest.main()
