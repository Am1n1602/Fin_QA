"""run_structured_checks against the engine fixture + a segment-carrying view."""
from __future__ import annotations

import unittest

from finqa_v2.crossval.checks import _margin_bridge_check, _segment_check, run_structured_checks
from finqa_v2.crossval.models import ManagementClaim
from finqa_v2.crossval.tests._fixture import engine_repos, growth_view
from finqa_v2.evidence import EvidenceSet


def _claim(**kw):
    base = dict(raw="mgmt claim", kind="generic")
    base.update(kw)
    return ManagementClaim(**base)


class TestStructuredChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.repos = engine_repos()

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def test_directional_agrees(self):
        ws = EvidenceSet()
        claim = _claim(kind="directional", subject="revenue", direction="increase")
        checks, view, change = run_structured_checks(self.engine, "TEST", claim, workspace=ws)
        d = next(c for c in checks if c.name == "directional")
        self.assertEqual(d.verdict, "agrees")     # fixture revenue 1000 -> 1200
        self.assertTrue(d.evidence_ids)

    def test_directional_contradicts(self):
        claim = _claim(kind="directional", subject="revenue", direction="decrease")
        checks, _, _ = run_structured_checks(self.engine, "TEST", claim)
        self.assertEqual(next(c for c in checks if c.name == "directional").verdict, "contradicts")

    def test_magnitude_close_enough(self):
        claim = _claim(kind="magnitude", subject="revenue", direction="increase",
                       claimed_value=20.0, claimed_unit="pct")
        checks, _, _ = run_structured_checks(self.engine, "TEST", claim)
        self.assertEqual(next(c for c in checks if c.name == "magnitude").verdict, "agrees")

    def test_magnitude_overstated(self):
        claim = _claim(kind="magnitude", subject="revenue", direction="increase",
                       claimed_value=40.0, claimed_unit="pct")
        checks, _, _ = run_structured_checks(self.engine, "TEST", claim)
        self.assertEqual(next(c for c in checks if c.name == "magnitude").verdict, "contradicts")

    def test_volume_mechanism_is_no_data(self):
        claim = _claim(kind="growth_driver", subject="revenue", direction="increase",
                       mechanism="volume", mechanism_kind="volume_pricing")
        checks, _, _ = run_structured_checks(self.engine, "TEST", claim)
        mech = next(c for c in checks if c.name == "mechanism")
        self.assertEqual(mech.verdict, "no_data")
        self.assertIn("volume", mech.detail)

    def test_cost_control_uses_expense_effect(self):
        # fixture FY25->FY26: revenue +20%, expenses +16.5% -> expense effect helps the margin
        claim = _claim(kind="margin_move", subject="net_profit_margin", direction="increase",
                       mechanism="cost_control", mechanism_kind="cost")
        checks, _, _ = run_structured_checks(self.engine, "TEST", claim)
        self.assertEqual(next(c for c in checks if c.name == "mechanism").verdict, "agrees")


class TestViewLevelChecks(unittest.TestCase):
    def test_margin_bridge_agrees_on_expansion(self):
        c = _margin_bridge_check(
            ManagementClaim(raw="x", kind="margin_move", direction="increase"),
            growth_view("increase"))
        self.assertEqual(c.verdict, "agrees")

    def test_margin_bridge_contradicts_when_margin_fell(self):
        c = _margin_bridge_check(
            ManagementClaim(raw="x", kind="margin_move", direction="increase"),
            growth_view("decrease"))
        self.assertEqual(c.verdict, "contradicts")

    def test_segment_acronym_match(self):
        c = _segment_check(
            ManagementClaim(raw="x", kind="segment_strength", mechanism="BFSI",
                            mechanism_kind="segment"),
            growth_view("increase"))
        self.assertEqual(c.verdict, "agrees")        # BFSI -> Banking Financial Services and Insurance, 75%
        self.assertIn("ev-seg-bfsi", c.evidence_ids)

    def test_segment_no_match(self):
        c = _segment_check(
            ManagementClaim(raw="x", kind="segment_strength", mechanism="Pharmaceuticals",
                            mechanism_kind="segment"),
            growth_view("increase"))
        self.assertEqual(c.verdict, "no_data")


if __name__ == "__main__":
    unittest.main()
