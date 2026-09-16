"""Verifier over real orchestrator output against finqa_v2.db (deterministic path)."""
from __future__ import annotations

import json
import os
import unittest

from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories


@unittest.skipUnless(DEFAULT_V2_DB_PATH.exists(), "needs database/data/finqa_v2.db")
class TestVerifierReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from finqa_v2.reasoning import ReasoningOrchestrator

        cls.repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        if cls.repos.companies.resolve("TCS") is None:
            raise unittest.SkipTest("TCS not in db")
        cls.orch = ReasoningOrchestrator(cls.repos)   # NullProvider (deterministic answers)

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_numeric_fact_passes_verification(self):
        r = self.orch.answer("What was TCS ROE in FY2026?")
        v = r.verification
        self.assertEqual(v["status"], "passed")
        self.assertFalse(v["abstained"])
        self.assertNotIn("[unverified]", r.answer)
        # the deterministic ROE calc is re-run independently
        self.assertGreaterEqual(v["counts"].get("recomputed", 0), 1)
        self.assertEqual(v["counts"].get("mismatch", 0), 0)
        json.dumps(r.to_dict())

    def test_trend_figures_reconcile(self):
        r = self.orch.answer("How has TCS revenue changed over the years?")
        v = r.verification
        self.assertEqual(v["counts"].get("mismatch", 0), 0)
        self.assertGreaterEqual(v["counts"].get("confirmed", 0), 1)

    def test_causal_answer_skips_number_pass_but_still_checks_citations(self):
        r = self.orch.answer("Why did HCLTECH profitability decline?")
        v = r.verification
        self.assertFalse(any(c["kind"] == "numeric" for c in v["checks"]))
        self.assertTrue(any(c["kind"] in ("citation", "support") for c in v["checks"]))
        self.assertFalse(v["abstained"])

    def test_every_claim_citation_is_live(self):
        for q in ("What was TCS ROE in FY2026?",
                  "Compare TCS and Infosys on ROE.",
                  "Why did HCLTECH profitability decline?"):
            r = self.orch.answer(q)
            missing = [c for c in r.verification["checks"] if c["verdict"] == "citation_missing"]
            self.assertEqual(missing, [], f"{q}: {missing}")


if __name__ == "__main__":
    unittest.main()
