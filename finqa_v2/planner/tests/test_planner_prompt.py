"""Prompt build + JSON parse + QueryPlanner facade (fake provider, no tokens)."""
from __future__ import annotations

import json
import unittest

from finqa_v2.llm.provider import LLMError
from finqa_v2.planner.models import Intent
from finqa_v2.planner.planner import QueryPlanner
from finqa_v2.planner.prompt import build_prompt, parse_plan
from finqa_v2.planner.tests._fixture import seed
from finqa_v2.sqlite import SqliteRepositories

_TOOLS = {"get_metric", "get_ratio", "get_growth", "search_documents", "compare_companies"}
_TICKERS = {"TCS", "INFY", "RELIANCE"}


class FakeProvider:
    name = "fake"

    def __init__(self, reply):
        self._reply = reply
        self.calls = 0

    def complete(self, prompt, *, system=None, json_object=False, temperature=0.1, max_tokens=1024):
        self.calls += 1
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


class TestPrompt(unittest.TestCase):
    def test_build_prompt_contains_catalog(self):
        p = build_prompt("Why did TCS revenue rise?",
                         tool_catalog=[("get_growth", "growth"), ("search_documents", "docs")],
                         known_tickers=["TCS", "INFY"])
        self.assertIn("get_growth: growth", p)
        self.assertIn("TCS, INFY", p)
        self.assertIn("Question: Why did TCS revenue rise?", p)

    def test_parse_good(self):
        raw = json.dumps({"intent": "causal", "companies": ["TCS"], "periods": ["FY2026"],
                          "metrics": ["revenue"], "tools": ["get_growth", "search_documents"],
                          "sub_questions": [], "needs_documents": True, "needs_calculation": True})
        plan = parse_plan("q", raw, valid_tools=_TOOLS, valid_tickers=_TICKERS)
        self.assertIs(plan.intent, Intent.CAUSAL)
        self.assertEqual(plan.companies, ["TCS"])
        self.assertTrue(plan.needs_documents)
        self.assertEqual(plan.planner, "llm")

    def test_parse_json_in_prose(self):
        raw = "Sure! Here is the plan:\n{\"intent\": \"numeric_fact\", \"companies\": [\"INFY\"], \"tools\": [\"get_ratio\"]}\nHope that helps."
        plan = parse_plan("q", raw, valid_tools=_TOOLS, valid_tickers=_TICKERS)
        self.assertIsNotNone(plan)
        self.assertIs(plan.intent, Intent.NUMERIC_FACT)

    def test_parse_drops_unknown_tools_and_tickers(self):
        raw = json.dumps({"intent": "comparison", "companies": ["TCS", "FOOBAR"],
                          "tools": ["compare_companies", "cast_spell"]})
        plan = parse_plan("q", raw, valid_tools=_TOOLS, valid_tickers=_TICKERS)
        self.assertEqual(plan.companies, ["TCS"])
        self.assertEqual(plan.tools, ["compare_companies"])
        self.assertEqual(plan.planner, "llm+repair")
        self.assertTrue(any("unknown" in n for n in plan.notes))

    def test_parse_bad(self):
        self.assertIsNone(parse_plan("q", "not json at all", valid_tools=_TOOLS, valid_tickers=_TICKERS))
        self.assertIsNone(parse_plan("q", "[1, 2, 3]", valid_tools=_TOOLS, valid_tickers=_TICKERS))
        self.assertIsNone(parse_plan("q", "{bad json", valid_tools=_TOOLS, valid_tickers=_TICKERS))


class TestQueryPlanner(unittest.TestCase):
    def setUp(self):
        self.repos = SqliteRepositories(":memory:")
        self.addCleanup(self.repos.close)
        seed(self.repos)

    def test_null_provider_uses_rules(self):
        p = QueryPlanner(self.repos).plan("What was TCS revenue in FY2026?")
        self.assertEqual(p.planner, "rules")
        self.assertEqual(p.companies, ["TCS"])

    def test_llm_provider_good_json(self):
        fake = FakeProvider(json.dumps({
            "intent": "causal", "companies": ["TCS"], "periods": ["FY2026"],
            "metrics": ["revenue"], "tools": ["get_growth", "search_documents"],
            "needs_documents": True, "needs_calculation": True}))
        p = QueryPlanner(self.repos, provider=fake).plan("Why did TCS revenue rise in FY2026?")
        self.assertEqual(fake.calls, 1)
        self.assertIs(p.intent, Intent.CAUSAL)
        self.assertIn("search_documents", p.tools)
        self.assertTrue(p.planner.startswith("llm"))

    def test_llm_garbage_falls_back_to_rules(self):
        p = QueryPlanner(self.repos, provider=FakeProvider("i cannot help with that")).plan(
            "Compare TCS and Infosys on ROE")
        self.assertEqual(p.planner, "rules")
        self.assertIs(p.intent, Intent.COMPARISON)
        self.assertIn("compare_companies", p.tools)

    def test_llm_error_falls_back_to_rules(self):
        p = QueryPlanner(self.repos, provider=FakeProvider(LLMError("boom"))).plan("TCS revenue")
        self.assertEqual(p.planner, "rules")
        self.assertTrue(any("unavailable" in n for n in p.notes))

    def test_merge_backfills_missing_company(self):
        # LLM returns valid JSON but forgot the company; rules backfills it
        fake = FakeProvider(json.dumps({"intent": "numeric_fact", "companies": [],
                                        "tools": ["get_metric"]}))
        p = QueryPlanner(self.repos, provider=fake).plan("What was Infosys revenue?")
        self.assertEqual(p.companies, ["INFY"])


if __name__ == "__main__":
    unittest.main()
