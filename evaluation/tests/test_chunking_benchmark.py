import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database" / "data" / "finqa_v2.db"
RAW_TCS = ROOT / "data_extraction" / "data" / "raw" / "TCS"


@unittest.skipUnless(DB.exists() and RAW_TCS.exists(), "finqa_v2.db / sample raw PDFs not available")
class Run(unittest.TestCase):
    def test_smoke_one_ticker_two_configs(self):
        """Not the full sample/config sweep (that's a deliberate multi-minute benchmark
        run, not a unit test) -- just proves the pipeline (extract -> chunk -> scratch db
        -> gold -> bm25 -> retrieve) works end to end without error, on a tiny slice."""
        from evaluation.benchmarks.chunking import run

        results = run(
            out_dir=ROOT / "database" / "data" / "chunking_bench_test",
            configs={"500": {"target": 500, "overlap": 70}, "900_current": {"target": 900, "overlap": 120}},
            tickers=["TCS"], pdfs_per_ticker=2,
            quotas={"numeric": 3, "narrative": 3},
        )
        self.assertEqual(set(results.keys()), {"500", "900_current"})
        for name, r in results.items():
            self.assertGreater(r["n_chunks"], 0, name)
            for key in ("recall@5", "recall@10", "mrr", "ndcg@5"):
                self.assertIn(key, r)

    def test_smaller_target_produces_more_chunks(self):
        from evaluation.benchmarks.chunking import run

        results = run(
            out_dir=ROOT / "database" / "data" / "chunking_bench_test2",
            configs={"500": {"target": 500, "overlap": 70}, "1200": {"target": 1200, "overlap": 160}},
            tickers=["TCS"], pdfs_per_ticker=2, quotas={"numeric": 3},
        )
        self.assertGreaterEqual(results["500"]["n_chunks"], results["1200"]["n_chunks"])


if __name__ == "__main__":
    unittest.main()
