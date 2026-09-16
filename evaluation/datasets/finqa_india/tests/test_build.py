import json
import unittest
from pathlib import Path

from evaluation.datasets.finqa_india.audit import audit, scaled_quotas

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "finqa_india.jsonl"

_SCHEMA = {"id", "category", "question", "companies", "period", "answer_type",
           "expected_intent", "should_abstain", "gold_spec", "reference_value",
           "reference_unit", "reference_answer", "reference_sources", "tolerance_pct",
           "must_contain", "notes"}


class BuiltArtifact(unittest.TestCase):
    """Validates the committed evaluation/datasets/finqa_india.jsonl."""

    @classmethod
    def setUpClass(cls):
        if not DATASET.exists():
            raise unittest.SkipTest("finqa_india.jsonl not built")
        cls.rows = [json.loads(l) for l in DATASET.read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_uniform_schema(self):
        for r in self.rows:
            self.assertEqual(set(r), _SCHEMA, r.get("id"))

    def test_ids_unique(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_quota_and_size(self):
        a = audit(self.rows, target=len(self.rows) if self.rows else 850)
        self.assertGreaterEqual(a["n"], 500)
        self.assertEqual(a["dup_questions"], 0)
        want = scaled_quotas(850)
        for cat, n in want.items():
            self.assertGreaterEqual(a["by_category"].get(cat, 0), int(n * 0.8), cat)

    def test_numeric_rows_carry_gold(self):
        num = [r for r in self.rows if r["answer_type"] == "numeric"]
        self.assertTrue(num)
        self.assertTrue(all(isinstance(r["reference_value"], (int, float)) for r in num))
        self.assertTrue(all(r["gold_spec"] for r in num))

    def test_adversarial_rows_are_abstain(self):
        adv = [r for r in self.rows if r["category"] == "adversarial"]
        self.assertTrue(all(r["should_abstain"] and r["answer_type"] == "abstain" for r in adv))

    def test_cross_document_rows_have_reference_section(self):
        xd = [r for r in self.rows if r["category"] == "cross_document"]
        self.assertTrue(all(r["reference_sources"] and r["reference_sources"][0].get("section")
                            for r in xd))


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class BuildFresh(unittest.TestCase):
    def test_small_target_build_is_balanced(self):
        from finqa_v2.engine import FinancialEngine
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.datasets.finqa_india.build import build

        repos = SqliteRepositories(DB)
        try:
            recs = build(repos, FinancialEngine(repos), target=200, seed=3)
        finally:
            repos.close()
        a = audit(recs, target=200)
        self.assertGreaterEqual(a["n"], 150)
        self.assertEqual(a["dup_questions"], 0)
        self.assertGreaterEqual(a["distinct_companies"], 20)
        # deterministic
        repos = SqliteRepositories(DB)
        try:
            recs2 = build(repos, FinancialEngine(repos), target=200, seed=3)
        finally:
            repos.close()
        self.assertEqual([r["question"] for r in recs], [r["question"] for r in recs2])


if __name__ == "__main__":
    unittest.main()
