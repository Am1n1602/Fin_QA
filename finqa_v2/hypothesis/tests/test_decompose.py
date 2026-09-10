"""build_decomposition against the engine fixture."""
from __future__ import annotations

import unittest

from finqa_v2.evidence import EvidenceSet
from finqa_v2.hypothesis.decompose import build_decomposition
from finqa_v2.hypothesis.detect import detect_metric_change
from finqa_v2.hypothesis.tests._fixture import engine_repos


class TestDecompose(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.repos = engine_repos()

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def setUp(self):
        self.ws = EvidenceSet()
        self.change = detect_metric_change(self.engine, "TEST", "net_profit", workspace=self.ws)

    def test_components_and_bridge(self):
        view = build_decomposition(self.engine, self.change, workspace=self.ws)
        self.assertIn("revenue", view.components)
        self.assertIn("total_expenses", view.components)
        self.assertAlmostEqual(view.components["revenue"]["pct"], 20.0, places=1)
        self.assertIsNotNone(view.margin_bridge)
        self.assertLess(view.margin_bridge["expense_effect_pp"], 0)   # costs ate into the margin
        self.assertGreater(view.margin_bridge["revenue_effect_pp"], 0)

    def test_dupont_delta(self):
        view = build_decomposition(self.engine, self.change)
        self.assertIsNotNone(view.dupont)
        self.assertIn("net_profit_margin", view.dupont)
        self.assertAlmostEqual(view.dupont["net_profit_margin"]["delta"], 2.5, places=2)

    def test_evidence_keyed_and_summarised(self):
        view = build_decomposition(self.engine, self.change, workspace=self.ws)
        self.assertIn("component_growth:revenue", view.evidence)
        self.assertIn("margin_bridge", view.evidence)
        self.assertTrue(view.all_evidence_ids())
        for eid in view.all_evidence_ids():
            self.assertIsNotNone(self.ws.get(eid))
        summ = view.summary()
        self.assertIn("revenue_growth_pct", summ)
        self.assertIn("expense_effect_pp", summ)

    def test_no_segments_is_empty_not_error(self):
        view = build_decomposition(self.engine, self.change)
        self.assertEqual(view.segments, [])


if __name__ == "__main__":
    unittest.main()
