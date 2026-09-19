"""Evidence Quality Gate: a safety floor on DOCUMENT evidence for causal/narrative claims."""
from __future__ import annotations

import unittest

from finqa_v2.evidence.models import Evidence, EvidenceType
from finqa_v2.evidence.quality_gate import check


def _doc(evidence_id, *, confidence, document_id=1):
    return Evidence(evidence_id=evidence_id, type=EvidenceType.DOCUMENT,
                    text="passage", document_id=document_id, confidence=confidence)


class TestQualityGate(unittest.TestCase):
    def test_no_evidence_fails(self):
        r = check([])
        self.assertFalse(r.passed)
        self.assertIn("no document evidence was retrieved", r.reasons[0])

    def test_strong_single_passage_passes(self):
        r = check([_doc("e1", confidence=0.8)])
        self.assertTrue(r.passed)
        self.assertEqual(r.reasons, [])

    def test_weak_confidence_fails_with_a_specific_reason(self):
        r = check([_doc("e1", confidence=0.3), _doc("e2", confidence=0.2)])
        self.assertFalse(r.passed)
        self.assertTrue(any("confidence" in reason for reason in r.reasons))

    def test_signals_report_the_actual_numbers(self):
        r = check([_doc("e1", confidence=0.9, document_id=1),
                  _doc("e2", confidence=0.6, document_id=2)])
        self.assertEqual(r.signals["count"], 2)
        self.assertAlmostEqual(r.signals["top_score"], 0.9)
        self.assertEqual(r.signals["diversity"], 2)


if __name__ == "__main__":
    unittest.main()
