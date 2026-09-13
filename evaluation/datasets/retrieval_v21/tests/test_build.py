import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "retrieval_v21.json"

_SCHEMA_REQUIRED = {"id", "question", "company", "period", "intent", "gold_chunks",
                    "gold_sections", "difficulty"}


@unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.sqlite import SqliteRepositories

        from evaluation.datasets.retrieval_v21.build import QUOTAS, build

        cls.repos = SqliteRepositories(DB)
        cls.records = build(cls.repos, seed=21)
        cls.quotas = QUOTAS

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_total_meets_acceptance_criterion(self):
        self.assertGreaterEqual(len(self.records), 300)

    def test_category_minimums_met(self):
        counts = Counter(r["intent"] for r in self.records)
        for cat, quota in self.quotas.items():
            self.assertGreaterEqual(counts.get(cat, 0), quota, cat)

    def test_non_adversarial_have_gold_evidence(self):
        for r in self.records:
            if r["intent"] not in ("adversarial", "no_evidence"):
                self.assertTrue(r["gold_chunks"], r["id"])
                self.assertTrue(r["gold_sections"], r["id"])

    def test_adversarial_and_no_evidence_have_empty_gold(self):
        for r in self.records:
            if r["intent"] in ("adversarial", "no_evidence"):
                self.assertEqual(r["gold_chunks"], [])

    def test_gold_chunk_ids_resolve_in_the_real_corpus(self):
        conn = self.repos.connection
        all_ids = {row[0] for row in conn.execute("SELECT chunk_id FROM document_chunks")}
        for r in self.records:
            for cid in r["gold_chunks"]:
                self.assertIn(cid, all_ids, r["id"])

    def test_ids_unique(self):
        ids = [r["id"] for r in self.records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_deterministic_for_a_fixed_seed(self):
        from evaluation.datasets.retrieval_v21.build import build

        again = build(self.repos, seed=21)
        self.assertEqual([r["id"] for r in again], [r["id"] for r in self.records])


@unittest.skipUnless(DATASET.exists(), "retrieval_v21.json not built")
class BuiltArtifact(unittest.TestCase):
    """Validates the committed evaluation/datasets/retrieval_v21.json without regenerating it."""

    @classmethod
    def setUpClass(cls):
        cls.records = json.loads(DATASET.read_text(encoding="utf-8"))

    def test_every_record_has_the_required_fields(self):
        for r in self.records:
            self.assertTrue(_SCHEMA_REQUIRED.issubset(r), r.get("id"))

    def test_every_record_has_a_query_type(self):
        for r in self.records:
            self.assertTrue(r["intent"])

    def test_total_and_category_minimums(self):
        from evaluation.datasets.retrieval_v21.build import QUOTAS

        self.assertGreaterEqual(len(self.records), 300)
        counts = Counter(r["intent"] for r in self.records)
        for cat, quota in QUOTAS.items():
            self.assertGreaterEqual(counts.get(cat, 0), quota, cat)


if __name__ == "__main__":
    unittest.main()
