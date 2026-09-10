import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "database" / "data" / "finqa_v2.db"


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class Generate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.engine import FinancialEngine
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.datasets.finqa_india.generate import generate

        cls.repos = SqliteRepositories(DB)
        cls.gen = generate(cls.repos, FinancialEngine(cls.repos), seed=7)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_all_categories_produced(self):
        for cat in ("factual", "numerical", "comparison", "multi_step", "why", "how",
                    "causal", "cross_document", "analytical", "adversarial"):
            self.assertTrue(self.gen.get(cat), cat)

    def test_numeric_candidates_have_resolved_gold(self):
        for cat in ("factual", "numerical"):
            for r in self.gen[cat]:
                self.assertEqual(r["answer_type"], "numeric")
                self.assertIsInstance(r["reference_value"], float)
                self.assertIsNotNone(r["reference_unit"])
                self.assertEqual(r["gold_spec"]["ticker"], r["companies"][0])

    def test_adversarial_all_abstain(self):
        for r in self.gen["adversarial"]:
            self.assertTrue(r["should_abstain"])
            self.assertEqual(r["answer_type"], "abstain")

    def test_comparison_names_two_companies(self):
        for r in self.gen["comparison"]:
            self.assertGreaterEqual(len(r["companies"]), 2)
            self.assertTrue(r["must_contain"])

    def test_punctuation_tickers_use_display_name(self):
        for cat in self.gen.values():
            for r in cat:
                self.assertNotIn("M&M's", r["question"])
                self.assertNotIn("BAJAJ-AUTO's", r["question"])

    def test_questions_nonempty_and_end_sensibly(self):
        for cat in self.gen.values():
            for r in cat:
                self.assertTrue(r["question"].strip())
                self.assertNotIn("{", r["question"])


if __name__ == "__main__":
    unittest.main()
