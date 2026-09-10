"""Deterministic planner: company / period / metric / intent / tool extraction."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from finqa_v2.planner.models import Intent
from finqa_v2.planner.rules import CompanyMatcher, plan_with_rules
from finqa_v2.planner.tests._fixture import seed
from finqa_v2.sqlite import SqliteRepositories


class PlannerRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)
        self.matcher = CompanyMatcher(self.repos)

    def _plan(self, q):
        return plan_with_rules(q, matcher=self.matcher)


class TestCompanyMatcher(PlannerRulesTestCase):
    def test_ticker_alias_name(self):
        self.assertEqual(self.matcher.find("What was TCS revenue?"), ["TCS"])
        self.assertEqual(self.matcher.find("What was Infosys' ROE?"), ["INFY"])
        self.assertEqual(self.matcher.find("How is Reliance doing?"), ["RELIANCE"])
        self.assertEqual(self.matcher.find("HDFC Bank net profit"), ["HDFCBANK"])

    def test_multi_company_order(self):
        self.assertEqual(self.matcher.find("Compare TCS and Infosys"), ["TCS", "INFY"])
        self.assertEqual(
            self.matcher.find("Bajaj Finance vs Bajaj Finserv on leverage"),
            ["BAJFINANCE", "BAJAJFINSV"],
        )

    def test_no_company(self):
        self.assertEqual(self.matcher.find("Which companies have the best margins?"), [])


class TestExtraction(PlannerRulesTestCase):
    def test_periods(self):
        self.assertEqual(self._plan("TCS revenue in FY2026").periods, ["FY2026"])
        self.assertEqual(self._plan("TCS revenue in FY26 Q1").periods, ["FY2026Q1"])
        self.assertEqual(self._plan("revenue for 2026").periods, ["FY2026"])
        self.assertIn("latest", self._plan("TCS latest revenue").periods)
        p = self._plan("How has TCS revenue changed over the last three years?")
        self.assertTrue(any("last 3 years" in n for n in p.notes))

    def test_metrics(self):
        self.assertEqual(self._plan("TCS revenue").metrics, ["revenue"])
        self.assertEqual(self._plan("Infosys return on equity").metrics, ["roe"])
        self.assertIn("net_profit_margin", self._plan("Compare TCS and INFY profitability").metrics)
        self.assertIn("debt_to_equity", self._plan("which has better leverage").metrics)


class TestIntentAndTools(PlannerRulesTestCase):
    CASES = [
        ("What was TCS revenue in FY2026?", Intent.NUMERIC_FACT, "get_metric"),
        ("What was Infosys' ROE?", Intent.NUMERIC_FACT, "get_ratio"),
        ("How has TCS revenue changed over five years?", Intent.TREND, "get_growth"),
        ("Compare TCS and Infosys on profitability.", Intent.COMPARISON, "compare_companies"),
        ("Rank companies by return on equity.", Intent.RANKING, "compare_companies"),
        ("Why did HCLTECH profitability decline?", Intent.CAUSAL, "search_documents"),
        ("Which segment contributed most to Reliance's revenue growth?", Intent.SEGMENT, "get_segment_data"),
        ("Management said Infosys growth came from volumes. Is this supported?",
         Intent.CROSS_VALIDATION, "search_documents"),
        ("Give me a fundamental overview of ITC.", Intent.RESEARCH_OVERVIEW, "get_ratio"),
    ]

    def test_cases(self):
        for q, intent, must_tool in self.CASES:
            p = self._plan(q)
            self.assertIs(p.intent, intent, msg=f"{q!r} -> {p.intent}")
            self.assertIn(must_tool, p.tools, msg=f"{q!r} tools={p.tools}")

    def test_causal_needs_documents(self):
        self.assertTrue(self._plan("Why did TCS margin fall?").needs_documents)

    def test_comparison_needs_calculation(self):
        self.assertTrue(self._plan("Compare TCS and INFY on ROE").needs_calculation)

    def test_planner_tag(self):
        self.assertEqual(self._plan("TCS revenue").planner, "rules")


class TestEvalCasesShakeout(PlannerRulesTestCase):
    def test_rules_planner_on_shipped_cases(self):
        cases = [json.loads(l) for l in
                 (Path(__file__).resolve().parents[1] / "planner_eval_cases.jsonl")
                 .read_text().splitlines() if l.strip()]
        intent_hits = must_hits = 0
        for c in cases:
            p = self._plan(c["question"])
            intent_hits += p.intent.value == c["intent"]
            must_hits += set(c["must_tools"]).issubset(set(p.tools))
        # the rules baseline should be decent on these hand-written cases
        self.assertGreaterEqual(intent_hits / len(cases), 0.75)
        self.assertGreaterEqual(must_hits / len(cases), 0.75)


if __name__ == "__main__":
    unittest.main()
