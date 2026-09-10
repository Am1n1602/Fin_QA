"""CrossValidator end to end on the in-memory engine fixture (no LLM, no retriever)."""
from __future__ import annotations

import json
import unittest

from finqa_v2.crossval import CrossValidator
from finqa_v2.crossval.tests._fixture import engine_repos
from finqa_v2.evidence import ClaimStatus, EvidenceSet


class TestValidator(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.repos = engine_repos()

    @classmethod
    def tearDownClass(cls):
        cls.repos.close()

    def setUp(self):
        self.cv = CrossValidator(self.repos, engine=self.engine)  # NullProvider, no retriever

    def test_supported_direction_no_docs_is_partial(self):
        ws = EvidenceSet()
        r = self.cv.validate("Management said revenue grew strongly in FY2026. "
                             "Is that supported?", "TEST", workspace=ws)
        self.assertIsNotNone(r.claim)
        self.assertIs(r.status, ClaimStatus.PARTIALLY_SUPPORTED)  # numbers agree, no commentary
        self.assertEqual(r.doc_status, "absent")
        self.assertTrue(r.support_evidence_ids)
        for eid in r.support_evidence_ids:
            self.assertIsNotNone(ws.get(eid))
        self.assertEqual(len(r.steps), 4)

    def test_false_claim_is_not_supported(self):
        r = self.cv.validate("Management said net profit margin contracted in FY2026. "
                             "Is that visible in the statements?", "TEST")
        # fixture margin went 10% -> 12.5%, so a contraction claim is contradicted
        self.assertIs(r.status, ClaimStatus.NOT_SUPPORTED)
        self.assertTrue(any(c.verdict == "contradicts" for c in r.checks))

    def test_magnitude_overstated_flags_provisional(self):
        r = self.cv.validate("Management said revenue grew 45% in FY2026. Is that consistent "
                             "with the reported financials?", "TEST")
        mags = [c for c in r.checks if c.name == "magnitude"]
        self.assertTrue(mags and mags[0].verdict == "contradicts")

    def test_volume_claim_keeps_honest_limitation(self):
        r = self.cv.validate("Management said revenue growth was driven by higher volumes. "
                             "Do the reported financials support this?", "TEST")
        self.assertTrue(any("volume" in l and "cannot be checked" in l for l in r.limitations))
        self.assertIn(r.status, {ClaimStatus.PARTIALLY_SUPPORTED, ClaimStatus.INSUFFICIENT_EVIDENCE})

    def test_no_claim_returns_insufficient(self):
        r = self.cv.validate("What was TEST revenue in FY2026?", "TEST")
        self.assertIsNone(r.claim)
        self.assertIs(r.status, ClaimStatus.INSUFFICIENT_EVIDENCE)

    def test_report_json_serialisable(self):
        r = self.cv.validate("Management said margins expanded in FY2026. Is that borne out?", "TEST")
        json.dumps(r.to_dict())
        self.assertIn(r.to_dict()["status"],
                      {"supported", "partially_supported", "not_supported", "insufficient_evidence"})

    def test_render_and_answer_sentences(self):
        r = self.cv.validate("Management said revenue grew strongly. Is that supported?", "TEST")
        self.assertIn("MANAGEMENT CLAIM", r.render())
        self.assertTrue(r.answer_sentences())
        self.assertTrue(any("deterministic cross-validation" in l for l in r.answer_limitations()))


if __name__ == "__main__":
    unittest.main()
