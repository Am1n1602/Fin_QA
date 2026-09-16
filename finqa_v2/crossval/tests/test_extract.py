"""extract_claim: pull the checkable management assertion out of a question."""
from __future__ import annotations

import unittest

from finqa_v2.crossval.extract import extract_claim


class TestExtract(unittest.TestCase):
    def test_growth_driver_volume(self):
        c = extract_claim("Management said revenue growth was driven by higher volumes. "
                          "Do the reported financials support this?")
        self.assertIsNotNone(c)
        self.assertEqual(c.kind, "growth_driver")
        self.assertEqual(c.subject, "revenue")
        self.assertEqual(c.direction, "increase")
        self.assertEqual(c.mechanism, "volume")
        self.assertEqual(c.mechanism_kind, "volume_pricing")

    def test_margin_expansion(self):
        c = extract_claim("Management highlighted margin expansion. Is this visible in the "
                          "financial statements?")
        self.assertEqual(c.kind, "margin_move")
        self.assertEqual(c.subject, "net_profit_margin")
        self.assertEqual(c.direction, "increase")

    def test_segment_attribution(self):
        c = extract_claim("Management attributed growth to the BFSI segment. "
                          "Is that supported by segment data?")
        self.assertEqual(c.kind, "segment_strength")
        self.assertEqual(c.mechanism_kind, "segment")
        self.assertIn("BFSI", c.mechanism)

    def test_magnitude_and_period(self):
        c = extract_claim("Management said revenue grew 12% in FY2026. Is that consistent "
                          "with the reported financials?")
        self.assertEqual(c.kind, "magnitude")
        self.assertAlmostEqual(c.claimed_value, 12.0)
        self.assertEqual(c.claimed_unit, "pct")
        self.assertEqual(c.period, "FY2026")

    def test_bps_becomes_pp(self):
        c = extract_claim("Management said margins improved 150 bps. Is that borne out?")
        self.assertAlmostEqual(c.claimed_value, 1.5)
        self.assertEqual(c.claimed_unit, "pp")

    def test_driven_by_without_management_keyword(self):
        c = extract_claim("Growth was driven by cost discipline and operating leverage — "
                          "is that borne out?")
        self.assertEqual(c.mechanism_kind, "cost")
        self.assertEqual(c.mechanism, "cost_control")

    def test_plain_lookup_is_not_a_claim(self):
        self.assertIsNone(extract_claim("What was TCS revenue in FY2026?"))
        self.assertIsNone(extract_claim("Compare TCS and Infosys on profitability."))


if __name__ == "__main__":
    unittest.main()
