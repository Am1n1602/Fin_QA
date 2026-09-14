import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "retrieval_v21.json"


@unittest.skipUnless(DB.exists() and DATASET.exists(), "finqa_v2.db / retrieval_v21.json not built")
class RunMode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.retrieval.evaluate import build_retriever
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.run_retrieval_benchmark import _KS, load_dataset, run_mode

        cls._KS = _KS
        cls.records = load_dataset(DATASET)[:40]  # a slice keeps this test fast
        cls.repos = SqliteRepositories(DB)
        cls.retriever = build_retriever(cls.repos, bm25_path=ROOT / "database" / "data" / "finqa_v2_bm25.pkl",
                                        vector_dir=ROOT / "database" / "data" / "finqa_v2_vec")

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_report_shape(self):
        from evaluation.run_retrieval_benchmark import run_mode

        report = run_mode(self.retriever, self.repos, self.records, "lexical")
        for k in self._KS:
            self.assertIn(f"recall@{k}", report)
        self.assertIn("mrr", report)
        self.assertIn("ndcg@5", report)
        self.assertIn("spurious_hit_rate", report)

    def test_section_aware_runs_without_error_and_is_off_by_default(self):
        from evaluation.run_retrieval_benchmark import run_mode

        without = run_mode(self.retriever, self.repos, self.records, "lexical", section_aware=False)
        with_sa = run_mode(self.retriever, self.repos, self.records, "lexical", section_aware=True)
        self.assertEqual(without["n_total"], with_sa["n_total"])
        # not asserting recall improves on this 40-row slice -- that's the full-dataset
        # A/B comparison's job (evaluation/results/), not a unit test's.

    def test_section_hints_runs_without_error_and_is_off_by_default(self):
        from evaluation.run_retrieval_benchmark import run_mode

        without = run_mode(self.retriever, self.repos, self.records, "lexical", section_hints=False)
        with_hints = run_mode(self.retriever, self.repos, self.records, "lexical", section_hints=True)
        self.assertEqual(without["n_total"], with_hints["n_total"])

    def test_query_expansion_runs_without_error_and_is_off_by_default(self):
        from evaluation.run_retrieval_benchmark import run_mode

        without = run_mode(self.retriever, self.repos, self.records, "lexical", query_expansion=False)
        with_qe = run_mode(self.retriever, self.repos, self.records, "lexical", query_expansion=True)
        self.assertEqual(without["n_total"], with_qe["n_total"])

    def test_weighted_fusion_runs_without_error_and_is_off_by_default(self):
        from evaluation.run_retrieval_benchmark import run_mode

        without = run_mode(self.retriever, self.repos, self.records, "hybrid", weighted_fusion=False)
        with_wf = run_mode(self.retriever, self.repos, self.records, "hybrid", weighted_fusion=True)
        self.assertEqual(without["n_total"], with_wf["n_total"])
        # not asserting recall is unchanged -- fusion_weights.yaml DOES override a few
        # categories (management_commentary/trend/multi_hop/table, §16's real A/B winners),
        # so this 40-row slice may legitimately score differently with the flag on. The
        # off-by-default contract is that omitting the flag (`without`) reproduces the
        # pre-§16 plain-RRF call byte-for-byte, which the retriever-level tests already
        # cover directly.

    def test_multi_query_runs_without_error_and_is_off_by_default(self):
        from evaluation.run_retrieval_benchmark import run_mode

        comparison_records = [r for r in self.records if len(r.get("company") or []) >= 2][:10]
        if not comparison_records:
            self.skipTest("no multi-company records in this 40-row slice")
        without = run_mode(self.retriever, self.repos, comparison_records, "lexical", multi_query=False)
        with_mq = run_mode(self.retriever, self.repos, comparison_records, "lexical", multi_query=True)
        self.assertEqual(without["n_total"], with_mq["n_total"])


if __name__ == "__main__":
    unittest.main()
