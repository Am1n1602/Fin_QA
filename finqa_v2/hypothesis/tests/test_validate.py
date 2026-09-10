"""structural_check + classify on hand-built decomposition views."""
from __future__ import annotations

import unittest

from finqa_v2.evidence import ClaimStatus
from finqa_v2.hypothesis.generate import _mk
from finqa_v2.hypothesis.tests._fixture import decline_view
from finqa_v2.hypothesis.validate import classify, lexical_overlap, structural_check


class TestStructuralCheck(unittest.TestCase):
    def setUp(self):
        self.view = decline_view()   # net_profit fell 20%

    def test_margin_bridge_agrees(self):
        h = _mk("Costs grew faster than revenue", ("margin_bridge", "expense_effect"))
        verdict, note = structural_check(h, self.view)
        self.assertEqual(verdict, "agrees")
        self.assertIn("pp", note)

    def test_component_growth_contradicts_when_cost_actually_fell_behind(self):
        # claim says finance costs surged, but they grew slower than revenue
        h = _mk("Rising finance costs outpaced revenue growth", ("component_growth", "finance_costs"))
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "contradicts")

    def test_component_growth_agrees_for_employee_costs(self):
        h = _mk("Rising employee costs outpaced revenue", ("component_growth", "employee_expense"))
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "agrees")

    def test_dupont_unrelated_for_flat_factor(self):
        h = _mk("Driven by asset turnover", ("dupont", "asset_turnover"))
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "unrelated")       # turnover delta is 0.0

    def test_dupont_agrees_for_margin_factor(self):
        h = _mk("Driven by a change in net profit margin", ("dupont", "net_profit_margin"))
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "agrees")          # margin fell, ROE fell

    def test_segment_agrees_dominant_share(self):
        h = _mk("Widgets drove it", ("segment", "Widgets"))
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "agrees")

    def test_llm_cause_keyword_matched(self):
        h = _mk("A tight talent market pushed up salaries", None, origin="llm")
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "agrees")          # -> employee_expense proxy

    def test_llm_cause_no_proxy_is_no_data(self):
        h = _mk("A change in accounting policy for leases", None, origin="llm")
        verdict, _ = structural_check(h, self.view)
        self.assertEqual(verdict, "no_data")


class TestClassify(unittest.TestCase):
    def test_agrees_plus_docs_is_supported(self):
        h = _mk("x", ("margin_bridge", "expense_effect"))
        h.structural_check = "agrees"
        status, conf = classify(h, [0.7, 0.6])
        self.assertIs(status, ClaimStatus.SUPPORTED)
        self.assertGreater(conf, 0.8)

    def test_agrees_no_docs_is_partial(self):
        h = _mk("x", ("margin_bridge", "expense_effect"))
        h.structural_check = "agrees"
        status, _ = classify(h, [])
        self.assertIs(status, ClaimStatus.PARTIALLY_SUPPORTED)

    def test_contradicts_is_not_supported(self):
        h = _mk("x", ("dupont", "asset_turnover"))
        h.structural_check = "contradicts"
        status, _ = classify(h, [0.8])
        self.assertIs(status, ClaimStatus.NOT_SUPPORTED)

    def test_no_data_no_docs_is_insufficient(self):
        h = _mk("x", None, origin="llm")
        h.structural_check = "no_data"
        status, _ = classify(h, [0.2])          # below the doc-confidence floor
        self.assertIs(status, ClaimStatus.INSUFFICIENT_EVIDENCE)

    def test_no_data_with_docs_is_partial(self):
        h = _mk("x", None, origin="llm")
        h.structural_check = "no_data"
        status, _ = classify(h, [0.6])
        self.assertIs(status, ClaimStatus.PARTIALLY_SUPPORTED)


class TestLexicalOverlap(unittest.TestCase):
    def test_counts_shared_content_tokens(self):
        self.assertGreaterEqual(
            lexical_overlap("rising employee wage costs", "attrition drove employee wage costs higher"), 2)
        self.assertEqual(lexical_overlap("employee costs", "the of and a"), 0)


if __name__ == "__main__":
    unittest.main()
