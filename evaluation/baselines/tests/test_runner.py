import json
import subprocess
import sys
import unittest
from pathlib import Path

from evaluation.baselines.runner import _rate, budget_split, load_dataset, stratified_sample

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "database" / "data" / "finqa_v2.db"
DATASET = ROOT / "evaluation" / "datasets" / "finqa_india.jsonl"


def _rec(cat, i):
    return {"id": f"{cat}-{i}", "category": cat, "question": f"q{i}"}


class StratifiedSample(unittest.TestCase):
    def test_covers_every_category(self):
        recs = [_rec(c, i) for c in ("a", "b", "c") for i in range(20)]
        s = stratified_sample(recs, 12, seed=1)
        cats = {r["category"] for r in s}
        self.assertEqual(cats, {"a", "b", "c"})

    def test_returns_all_when_n_exceeds_total(self):
        recs = [_rec("a", i) for i in range(5)]
        self.assertEqual(len(stratified_sample(recs, 50, seed=1)), 5)

    def test_deterministic_for_a_seed(self):
        recs = [_rec("a", i) for i in range(30)]
        s1 = stratified_sample(recs, 10, seed=7)
        s2 = stratified_sample(recs, 10, seed=7)
        self.assertEqual([r["id"] for r in s1], [r["id"] for r in s2])


class BudgetSplit(unittest.TestCase):
    def test_even_split_by_default(self):
        c = budget_split(["A", "B", "C", "D"], 4.0, None)
        self.assertEqual(c, {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0})

    def test_explicit_split_overrides_named_entries(self):
        c = budget_split(["A", "B", "C", "D"], 3.0, "D:1.35")
        self.assertEqual(c["D"], 1.35)
        # unmentioned baselines keep the even-split default, not a re-normalised remainder
        self.assertEqual(c["A"], 0.75)

    def test_unknown_names_in_spec_are_ignored(self):
        c = budget_split(["A", "B"], 2.0, "Z:5.0")
        self.assertEqual(c, {"A": 1.0, "B": 1.0})

    def test_single_baseline_gets_the_whole_cap(self):
        self.assertEqual(budget_split(["A"], 3.0, None), {"A": 3.0})


class Rate(unittest.TestCase):
    def test_rate_math(self):
        rows = [{"scores": {"numerical": {"verdict": v}}} for v in ("pass", "pass", "fail")]
        r = _rate(rows, "numerical")
        self.assertEqual((r["passed"], r["failed"], r["checked"]), (2, 1, 3))
        self.assertAlmostEqual(r["accuracy"], 2 / 3, places=4)


@unittest.skipUnless(DATASET.exists(), "finqa_india.jsonl not built")
class Cli(unittest.TestCase):
    def test_dry_run(self):
        out = subprocess.run(
            [sys.executable, "-m", "evaluation.baselines.runner", "--dataset", str(DATASET),
             "--sample", "10", "--dry-run"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("by category", out.stdout)

    @unittest.skipUnless(DB.exists(), "finqa_v2.db not built")
    def test_real_mini_run_deterministic(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            rep = Path(td) / "mini.json"
            out = subprocess.run(
                [sys.executable, "-m", "evaluation.baselines.runner", "--dataset", str(DATASET),
                 "--sample", "8", "--label", "test-mini", "--out", str(rep)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=300)
            self.assertEqual(out.returncode, 0, out.stderr)
            data = json.loads(rep.read_text())
            self.assertEqual(set(data["comparison"]), {"A_llm_only", "B_vector_rag",
                                                        "C_engine_llm", "D_full_finqa"})
            for name in data["comparison"]:
                self.assertEqual(len(data["results"][name]), data["comparison"][name]["n"])


if __name__ == "__main__":
    unittest.main()
