"""Unit tests for the individual §25 checks."""
from __future__ import annotations

import unittest

from finqa_v2.evidence import Evidence, EvidenceSet, EvidenceType
from finqa_v2.verification.checks import check_answer_numbers, check_calculation, check_claim


def _calc(**kw):
    base = dict(calculation_id="k1", kind="ratio", name="roe", result=25.0, unit="pct",
                expression="net_profit / total_equity * 100",
                inputs=[{"name": "net_profit", "value": 100.0},
                        {"name": "total_equity", "value": 400.0}], period="FY2026")
    base.update(kw)
    return base


class TestCheckCalculation(unittest.TestCase):
    def test_reproduces(self):
        c = check_calculation(_calc())
        self.assertEqual(c.verdict, "recomputed")

    def test_does_not_reproduce(self):
        c = check_calculation(_calc(result=45.6))
        self.assertEqual(c.verdict, "does_not_recompute")
        self.assertTrue(c.hard_fail)

    def test_growth_recomputed_from_endpoints(self):
        c = check_calculation(_calc(kind="growth", name="revenue_yoy", result=20.0,
                                    expression="(curr - prev) / prev * 100",
                                    inputs=[{"name": "revenue", "value": 1000.0},
                                            {"name": "revenue", "value": 1200.0}]))
        self.assertEqual(c.verdict, "recomputed")

    def test_missing_input_is_not_recomputable(self):
        c = check_calculation(_calc(expression="ebit / (total_assets - current_liabilities) * 100",
                                    inputs=[{"name": "total_assets", "value": 100.0}]))
        self.assertEqual(c.verdict, "not_recomputable")
        self.assertFalse(c.hard_fail)

    def test_no_result_skipped(self):
        self.assertEqual(check_calculation(_calc(result=None)).verdict, "skipped")


class TestCheckClaim(unittest.TestCase):
    def setUp(self):
        self.by_id = {"ev1": {"evidence_id": "ev1", "type": "ratio", "text": None},
                      "d1": {"evidence_id": "d1", "type": "document",
                             "text": "revenue rose on strong banking demand"}}

    def test_supported_and_cited(self):
        checks = check_claim({"claim_id": "c1", "text": "roe rose", "kind": "numeric",
                              "evidence_ids": ["ev1"], "calculation_ids": []}, self.by_id)
        verdicts = {c.verdict for c in checks}
        self.assertIn("supported", verdicts)
        self.assertIn("cited", verdicts)

    def test_unsupported(self):
        checks = check_claim({"claim_id": "c2", "text": "x", "kind": "qualitative",
                              "evidence_ids": [], "calculation_ids": []}, self.by_id)
        self.assertEqual(checks[0].verdict, "unsupported")
        self.assertTrue(checks[0].hard_fail)

    def test_citation_missing(self):
        checks = check_claim({"claim_id": "c3", "text": "x", "kind": "numeric",
                              "evidence_ids": ["ghost"], "calculation_ids": []}, self.by_id)
        self.assertTrue(any(c.verdict == "citation_missing" and c.hard_fail for c in checks))

    def test_doc_claim_weak_when_no_overlap(self):
        checks = check_claim({"claim_id": "c4", "text": "margins fell on rising litigation costs",
                              "kind": "causal", "evidence_ids": ["d1"], "calculation_ids": []},
                             self.by_id)
        self.assertTrue(any(c.verdict == "citation_weak" for c in checks))

    def test_doc_claim_ok_when_overlap(self):
        checks = check_claim({"claim_id": "c5", "text": "revenue rose on strong banking demand",
                              "kind": "causal", "evidence_ids": ["d1"], "calculation_ids": []},
                             self.by_id)
        self.assertFalse(any(c.verdict == "citation_weak" for c in checks))


class TestCheckAnswerNumbers(unittest.TestCase):
    def _ws(self):
        ws = EvidenceSet()
        ws.add(Evidence(evidence_id="r", type=EvidenceType.RATIO, company="TCS", metric="roe",
                        period="FY2026", value=45.6, unit="pct", confidence=0.9))
        ws.add(Evidence(evidence_id="g", type=EvidenceType.GROWTH, company="TCS",
                        metric="revenue_yoy", period="FY2025 -> FY2026", value=4.6, unit="pct",
                        confidence=0.9))
        return ws

    def test_confirms_matching_figure(self):
        checks = check_answer_numbers("TCS roe in FY2026 was 45.6 pct.", self._ws())
        self.assertTrue(any(c.verdict == "confirmed" for c in checks))

    def test_flags_wrong_figure(self):
        checks = check_answer_numbers("TCS roe in FY2026 was 62 pct.", self._ws())
        self.assertTrue(any(c.verdict == "mismatch" and c.hard_fail for c in checks))

    def test_period_mismatch_is_skipped(self):
        # sentence talks about FY2024, evidence is FY2026 -> no check emitted
        checks = check_answer_numbers("TCS roe in FY2024 was 30 pct.", self._ws())
        self.assertFalse([c for c in checks if "roe" in c.detail])

    def test_growth_figure_confirmed(self):
        checks = check_answer_numbers("Revenue grew 4.6% year on year.", self._ws())
        self.assertTrue(any(c.verdict == "confirmed" for c in checks))

    def test_ambiguous_sentence_not_a_hard_fail(self):
        checks = check_answer_numbers("Revenue growth was 4.6% versus 9.0% a year earlier.",
                                      self._ws())
        self.assertFalse(any(c.hard_fail for c in checks))


if __name__ == "__main__":
    unittest.main()
