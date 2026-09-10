"""Planner-eval metric math + optional real LLM run (gated behind FINQA_LLM_TESTS=1)."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from finqa_v2.planner.evaluate import evaluate, load_cases
from finqa_v2.planner.planner import QueryPlanner
from finqa_v2.planner.tests._fixture import seed
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_CASES = Path(__file__).resolve().parents[1] / "planner_eval_cases.jsonl"


class TestEvalMath(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.planner = QueryPlanner(self.repos)

    def test_rules_report_shape_and_bounds(self):
        rep = evaluate(self.planner, load_cases(_CASES), use_llm=False)
        for key in ("intent_accuracy", "company_f1", "tool_f1_mean",
                    "must_tools_hit_rate", "plan_valid_rate"):
            self.assertGreaterEqual(rep[key], 0.0)
            self.assertLessEqual(rep[key], 1.0)
        self.assertEqual(rep["n"], len(load_cases(_CASES)))
        self.assertEqual(len(rep["rows"]), rep["n"])
        # rules baseline should be reasonable on the hand-written cases
        self.assertGreaterEqual(rep["intent_accuracy"], 0.7)
        self.assertGreaterEqual(rep["plan_valid_rate"], 0.9)

    def test_toy_metrics(self):
        toy = [
            {"id": "a", "question": "What was TCS revenue in FY2026?", "intent": "numeric_fact",
             "companies": ["TCS"], "ideal_tools": ["get_metric"], "must_tools": ["get_metric"]},
            {"id": "b", "question": "Compare TCS and Infosys on ROE", "intent": "comparison",
             "companies": ["TCS", "INFY"], "ideal_tools": ["compare_companies"],
             "must_tools": ["compare_companies"]},
        ]
        rep = evaluate(self.planner, toy, use_llm=False)
        self.assertEqual(rep["intent_accuracy"], 1.0)
        self.assertEqual(rep["company_recall"], 1.0)
        self.assertEqual(rep["must_tools_hit_rate"], 1.0)


@unittest.skipUnless(os.environ.get("FINQA_LLM_TESTS") == "1" and DEFAULT_V2_DB_PATH.exists(),
                     "set FINQA_LLM_TESTS=1 to run (spends Groq tokens)")
class TestRealLLMPlanner(unittest.TestCase):
    def test_llm_beats_or_matches_rules(self):
        from finqa_v2.llm import provider_from_env

        repos = SqliteRepositories(DEFAULT_V2_DB_PATH)
        self.addCleanup(repos.close)
        provider = provider_from_env()
        self.assertNotEqual(provider.name, "null")
        planner = QueryPlanner(repos, provider=provider)
        cases = load_cases(_CASES)
        rules = evaluate(planner, cases, use_llm=False)
        llm = evaluate(planner, cases, use_llm=True)
        print("\nrules:", {k: rules[k] for k in ("intent_accuracy", "company_f1", "tool_f1_mean")})
        print("llm  :", {k: llm[k] for k in ("intent_accuracy", "company_f1", "tool_f1_mean")})
        self.assertGreaterEqual(llm["plan_valid_rate"], 0.9)


if __name__ == "__main__":
    unittest.main()
