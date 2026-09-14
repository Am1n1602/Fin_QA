import unittest
from dataclasses import dataclass

from finqa_v2.evidence.quality_gate import INSUFFICIENT_EVIDENCE, PASS, check


@dataclass
class _Doc:
    confidence: float = 0.5
    document_id: int | None = 1
    section: str | None = None
    company_id: int | None = None


class QualityGateCheck(unittest.TestCase):
    def test_no_docs_is_insufficient(self):
        r = check([])
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertTrue(r.reasons)
        self.assertFalse(r.sufficient)

    def test_single_strong_doc_passes(self):
        r = check([_Doc(confidence=0.8)])
        self.assertEqual(r.status, PASS)
        self.assertTrue(r.sufficient)

    def test_top_score_below_threshold_is_insufficient(self):
        r = check([_Doc(confidence=0.2)], min_top_score=0.4)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertTrue(any("confidence" in reason for reason in r.reasons))

    def test_top_score_uses_the_best_doc_not_the_average(self):
        r = check([_Doc(confidence=0.1), _Doc(confidence=0.9, document_id=2)], min_top_score=0.4)
        self.assertEqual(r.status, PASS)
        self.assertEqual(r.signals["top_score"], 0.9)

    def test_diversity_counts_distinct_documents(self):
        r = check([_Doc(confidence=0.8, document_id=1), _Doc(confidence=0.8, document_id=1)],
                  min_diversity=2)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertEqual(r.signals["diversity"], 1)

    def test_diversity_satisfied_by_distinct_documents(self):
        r = check([_Doc(confidence=0.8, document_id=1), _Doc(confidence=0.8, document_id=2)],
                  min_diversity=2)
        self.assertEqual(r.status, PASS)

    def test_expected_company_mismatch_is_insufficient(self):
        r = check([_Doc(confidence=0.8, company_id=5)], expected_company_id=9)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertFalse(r.signals["metadata_match"])

    def test_expected_company_match_passes(self):
        r = check([_Doc(confidence=0.8, company_id=9)], expected_company_id=9)
        self.assertEqual(r.status, PASS)

    def test_no_expected_company_is_always_a_metadata_match(self):
        r = check([_Doc(confidence=0.8, company_id=5)], expected_company_id=None)
        self.assertTrue(r.signals["metadata_match"])

    def test_section_outside_intent_hints_is_insufficient(self):
        # "causal" hints mda/earnings_call (real shipped section_weights.yaml) -- a
        # cover_letter-only result should fail the section-match check.
        r = check([_Doc(confidence=0.8, section="cover_letter")], intent="causal")
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)
        self.assertFalse(r.signals["section_match"])

    def test_section_matching_intent_hints_passes(self):
        r = check([_Doc(confidence=0.8, section="mda")], intent="causal")
        self.assertEqual(r.status, PASS)
        self.assertTrue(r.signals["section_match"])

    def test_unconfigured_intent_skips_section_check(self):
        r = check([_Doc(confidence=0.8, section="anything")], intent="some_unconfigured_intent")
        self.assertEqual(r.status, PASS)
        self.assertTrue(r.signals["section_match"])

    def test_no_intent_skips_section_check(self):
        r = check([_Doc(confidence=0.8, section="cover_letter")], intent=None)
        self.assertEqual(r.status, PASS)

    def test_none_confidence_docs_do_not_crash(self):
        r = check([_Doc(confidence=None)])
        self.assertEqual(r.signals["top_score"], 0.0)
        self.assertEqual(r.status, INSUFFICIENT_EVIDENCE)

    def test_multiple_reasons_all_reported(self):
        r = check([], min_count=1)
        self.assertGreaterEqual(len(r.reasons), 1)


if __name__ == "__main__":
    unittest.main()
