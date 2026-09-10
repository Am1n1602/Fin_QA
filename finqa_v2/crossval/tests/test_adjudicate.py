"""adjudicate: structured checks + doc status -> ClaimStatus."""
from __future__ import annotations

import unittest

from finqa_v2.crossval.adjudicate import adjudicate
from finqa_v2.crossval.models import CrossCheck, ManagementClaim
from finqa_v2.evidence import ClaimStatus


def _c(name, verdict):
    return CrossCheck(name, verdict, "")


_CLAIM = ManagementClaim(raw="x", kind="growth_driver", mechanism="volume",
                         mechanism_kind="volume_pricing")


class TestAdjudicate(unittest.TestCase):
    def test_agrees_plus_stated_is_supported(self):
        s, conf, _ = adjudicate(_CLAIM, [_c("directional", "agrees")], "stated")
        self.assertIs(s, ClaimStatus.SUPPORTED)
        self.assertGreater(conf, 0.8)

    def test_agrees_no_docs_is_partial(self):
        s, _, _ = adjudicate(_CLAIM, [_c("directional", "agrees")], "absent")
        self.assertIs(s, ClaimStatus.PARTIALLY_SUPPORTED)

    def test_contradicts_is_not_supported(self):
        s, _, _ = adjudicate(_CLAIM, [_c("directional", "contradicts"),
                                      _c("margin_bridge", "contradicts")], "absent")
        self.assertIs(s, ClaimStatus.NOT_SUPPORTED)

    def test_mixed_structured_is_partial_and_flagged(self):
        s, _, lims = adjudicate(_CLAIM, [_c("directional", "agrees"),
                                         _c("magnitude", "contradicts")], "absent")
        self.assertIs(s, ClaimStatus.PARTIALLY_SUPPORTED)
        self.assertTrue(any("disagree" in l for l in lims))

    def test_unprovable_mechanism_stated_is_partial_with_limitation(self):
        s, _, lims = adjudicate(_CLAIM, [_c("mechanism", "no_data")], "stated")
        self.assertIs(s, ClaimStatus.PARTIALLY_SUPPORTED)
        self.assertTrue(any("cannot be checked against structured data" in l for l in lims))

    def test_nothing_is_insufficient(self):
        s, _, _ = adjudicate(_CLAIM, [_c("mechanism", "no_data")], "absent")
        self.assertIs(s, ClaimStatus.INSUFFICIENT_EVIDENCE)

    def test_doc_contradicted_is_not_supported(self):
        s, _, _ = adjudicate(_CLAIM, [_c("directional", "unrelated")], "contradicted")
        self.assertIs(s, ClaimStatus.NOT_SUPPORTED)


if __name__ == "__main__":
    unittest.main()
