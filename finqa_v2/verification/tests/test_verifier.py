"""Verifier adjudication: pass / mark-uncertain / abstain, and the response mutations."""
from __future__ import annotations

import json
import unittest

from finqa_v2.evidence import Evidence, EvidenceSet, EvidenceType
from finqa_v2.verification import Verifier


def _ws():
    ws = EvidenceSet()
    ws.add(Evidence(evidence_id="ev1", type=EvidenceType.RATIO, company="TCS", metric="roe",
                    period="FY2026", value=45.6, unit="pct", confidence=0.9))
    return ws


def _response(**over):
    r = {
        "answer": "TCS roe in FY2026 was 45.6 pct.",
        "confidence": 0.9,
        "claims": [{"claim_id": "c1", "text": "TCS ROE was 45.6%", "kind": "numeric",
                    "evidence_ids": ["ev1"], "calculation_ids": ["k1"],
                    "status": "supported", "confidence": 0.9}],
        "calculations": [{"calculation_id": "k1", "kind": "ratio", "name": "roe", "result": 45.6,
                          "unit": "pct", "expression": "net_profit / total_equity * 100",
                          "inputs": [{"name": "net_profit", "value": 456.0},
                                     {"name": "total_equity", "value": 1000.0}],
                          "period": "FY2026"}],
        "evidence": [e.to_dict() for e in _ws()],
        "sources": [], "limitations": [],
    }
    r.update(over)
    return r


class TestVerifier(unittest.TestCase):
    def test_clean_response_passes_untouched(self):
        r = _response()
        rep = Verifier().verify(r, _ws())
        self.assertEqual(rep.status, "passed")
        self.assertFalse(rep.abstained)
        self.assertEqual(r["confidence"], 0.9)
        self.assertEqual(r["claims"][0]["status"], "supported")
        self.assertFalse(r["answer"].startswith("[unverified]"))

    def test_bad_calculation_flags_and_caps_confidence(self):
        r = _response(calculations=[{**_response()["calculations"][0], "result": 80.0}])
        rep = Verifier().verify(r, _ws())
        self.assertTrue(any(c.verdict == "does_not_recompute" for c in rep.checks))
        self.assertLessEqual(r["confidence"], 0.6)
        self.assertTrue(any("not reproduced" in l for l in r["limitations"]))

    def test_missing_citation_downgrades_claim(self):
        bad = _response()
        bad["claims"][0]["evidence_ids"] = ["ghost"]
        rep = Verifier().verify(bad, _ws())
        self.assertEqual(bad["claims"][0]["status"], "not_supported")
        self.assertLess(bad["claims"][0]["confidence"], 0.9)

    def test_wrong_headline_number_abstains(self):
        r = _response(answer="TCS roe in FY2026 was 62 pct, the best in its peer group.")
        rep = Verifier().verify(r, _ws())
        self.assertTrue(rep.abstained)
        self.assertTrue(r["answer"].startswith("[unverified]"))
        self.assertLessEqual(r["confidence"], 0.3)

    def test_check_numbers_false_skips_answer_pass(self):
        r = _response(answer="Margin fell -13.9% while the segment carried 74% of the change.")
        rep = Verifier().verify(r, _ws(), check_numbers=False)
        self.assertFalse(any(c.kind == "numeric" for c in rep.checks))
        self.assertEqual(rep.status, "passed")

    def test_report_json_serialisable(self):
        rep = Verifier().verify(_response(), _ws())
        json.dumps(rep.to_dict())
        self.assertIn("counts", rep.to_dict())


if __name__ == "__main__":
    unittest.main()
