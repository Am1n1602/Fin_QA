import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from evaluation.runners.v2_runner import _mean_metric, _rate, load_dataset

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "finqa_v2_eval.jsonl"


class Helpers(unittest.TestCase):
    def test_load_dataset(self):
        recs = load_dataset(DATASET)
        self.assertGreater(len(recs), 20)
        self.assertTrue(all("id" in r and "question" in r for r in recs))
        self.assertTrue(any(r.get("reference_value") is not None for r in recs))

    def test_rate(self):
        rows = [{"scores": {"numerical": {"verdict": v}}}
                for v in ("pass", "pass", "fail", "na")]
        r = _rate(rows, "numerical")
        self.assertEqual((r["passed"], r["failed"], r["checked"]), (2, 1, 3))
        self.assertEqual(r["accuracy"], round(2 / 3, 4))

    def test_mean_metric(self):
        rows = [{"scores": {"citation": {"metrics": {"f1": 0.5}}}},
                {"scores": {"citation": {"metrics": {"f1": 1.0}}}},
                {"scores": {"citation": {"metrics": {"f1": None}}}}]
        self.assertEqual(_mean_metric(rows, "citation", "f1"), 0.75)


class Cli(unittest.TestCase):
    def test_dry_run(self):
        out = subprocess.run(
            [sys.executable, "-m", "evaluation.runners.v2_runner",
             "--dataset", str(DATASET), "--dry-run"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("[dry-run] records", out.stdout)

    @unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
    def test_real_mini_run_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            rep = Path(td) / "mini.json"
            out = subprocess.run(
                [sys.executable, "-m", "evaluation.runners.v2_runner",
                 "--dataset", str(DATASET), "--filter-category", "numerical",
                 "--limit", "3", "--no-retriever", "--label", "test-mini",
                 "--out", str(rep)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=600)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(rep.read_text())
            self.assertEqual(data["aggregates"]["n_questions"], 3)
            self.assertIn("numerical", data["aggregates"])
            self.assertEqual(data["aggregates"]["errors"], 0)
            # deterministic engine truth should be surfaced in the answer text
            self.assertGreaterEqual(data["aggregates"]["numerical"]["passed"], 2)


if __name__ == "__main__":
    unittest.main()
