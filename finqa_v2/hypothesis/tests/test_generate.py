"""deterministic_candidates + generate_candidates (LLM merge)."""
from __future__ import annotations

import unittest

from finqa_v2.hypothesis.generate import deterministic_candidates, generate_candidates
from finqa_v2.hypothesis.models import MetricChange
from finqa_v2.hypothesis.tests._fixture import decline_view
from finqa_v2.hypothesis.decompose import DecompositionView


class _FakeProvider:
    name = "fake"

    def __init__(self, text):
        self._text = text
        self.calls = 0

    def complete(self, prompt, *, system=None, json_object=False, temperature=0.1, max_tokens=1024):
        self.calls += 1
        return self._text


class TestDeterministic(unittest.TestCase):
    def test_decline_flags_costs(self):
        hyps = deterministic_candidates(decline_view())
        self.assertTrue(hyps)
        sigs = {h.signal for h in hyps}
        self.assertIn(("margin_bridge", "expense_effect"), sigs)
        self.assertIn(("component_growth", "employee_expense"), sigs)
        # the segment that carried >40% of the revenue change
        self.assertIn(("segment", "Widgets"), sigs)
        self.assertTrue(all(h.origin == "deterministic" for h in hyps))

    def test_increase_direction_produces_positive_framing(self):
        change = MetricChange(
            ticker="ACME", metric="net_profit", basis="consolidated",
            from_period="FY2025", to_period="FY2026",
            from_value=100.0, to_value=140.0, abs_change=40.0, pct_change=40.0,
        )
        view = DecompositionView(
            change=change,
            components={"revenue": {"pct": 25.0}, "employee_expense": {"pct": 10.0}},
            margin_bridge={"expense_effect_pp": 1.2, "revenue_effect_pp": 0.1},
        )
        hyps = deterministic_candidates(view)
        self.assertTrue(hyps)
        self.assertTrue(any("widened the margin" in h.statement for h in hyps))
        self.assertTrue(any("lifting profit" in h.statement for h in hyps))

    def test_dedup_on_statement(self):
        hyps = deterministic_candidates(decline_view())
        stmts = [h.statement.lower() for h in hyps]
        self.assertEqual(len(stmts), len(set(stmts)))


class TestGenerateWithLLM(unittest.TestCase):
    def test_llm_causes_merged_and_tagged(self):
        p = _FakeProvider('{"causes": ["Wage inflation from a tight talent market", '
                          '"Deferred client ramp-ups delayed billing"]}')
        hyps = generate_candidates(decline_view(), "Why did profit fall?", provider=p)
        self.assertEqual(p.calls, 1)
        llm = [h for h in hyps if h.origin == "llm"]
        self.assertTrue(llm)
        self.assertIsNone(llm[0].signal)

    def test_llm_garbage_is_ignored(self):
        p = _FakeProvider("sorry, I cannot help with that")
        base = deterministic_candidates(decline_view())
        hyps = generate_candidates(decline_view(), "Why?", provider=p)
        self.assertEqual(len(hyps), len(base))

    def test_no_provider_is_deterministic_only(self):
        hyps = generate_candidates(decline_view(), "Why?", provider=None)
        self.assertTrue(all(h.origin == "deterministic" for h in hyps))


if __name__ == "__main__":
    unittest.main()
