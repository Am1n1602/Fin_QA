"""detect_metric_change: plain metric via YoY growth, ratio via endpoint diff."""
from __future__ import annotations

import unittest

from finqa_v2.evidence import EvidenceSet
from finqa_v2.hypothesis.detect import detect_metric_change
from finqa_v2.hypothesis.tests._fixture import engine_repos


class TestDetect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.repos = engine_repos()

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_plain_metric_uses_growth(self):
        ws = EvidenceSet()
        ch = detect_metric_change(self.engine, "TEST", "net_profit", workspace=ws)
        self.assertIsNotNone(ch)
        self.assertEqual(ch.direction, "increase")
        self.assertEqual(ch.from_period, "FY2025")
        self.assertEqual(ch.to_period, "FY2026")
        self.assertAlmostEqual(ch.from_value, 100.0)
        self.assertAlmostEqual(ch.to_value, 150.0)
        self.assertAlmostEqual(ch.pct_change, 50.0)
        self.assertIsNotNone(ch.evidence_id)
        self.assertTrue(len(ws) >= 1)

    def test_ratio_target_endpoint_diff(self):
        ch = detect_metric_change(self.engine, "TEST", "net_profit_margin")
        self.assertIsNotNone(ch)
        # FY2025 margin 10.0%, FY2026 12.5%
        self.assertAlmostEqual(ch.from_value, 10.0, places=3)
        self.assertAlmostEqual(ch.to_value, 12.5, places=3)
        self.assertAlmostEqual(ch.abs_change, 2.5, places=3)
        self.assertEqual(ch.direction, "increase")

    def test_default_metric_when_blank(self):
        ch = detect_metric_change(self.engine, "TEST", "")
        self.assertIsNotNone(ch)
        self.assertEqual(ch.metric, "net_profit")


if __name__ == "__main__":
    unittest.main()
