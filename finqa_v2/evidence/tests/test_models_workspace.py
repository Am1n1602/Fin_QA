"""Evidence / Citation / Calculation / Claim models + EvidenceSet."""
from __future__ import annotations

import unittest

from finqa_v2.evidence.models import (
    Calculation,
    Citation,
    Claim,
    ClaimStatus,
    Evidence,
    EvidenceType,
)
from finqa_v2.evidence.workspace import EvidenceSet


def _doc_ev(eid, doc_id, page, text, conf):
    return Evidence(evidence_id=eid, type=EvidenceType.DOCUMENT, text=text,
                    document_id=doc_id, page=page, confidence=conf)


def _fact_ev(eid, metric, value, conf=0.98):
    return Evidence(evidence_id=eid, type=EvidenceType.FINANCIAL_FACT, metric=metric,
                    value=value, unit="INR", period="FY2026", confidence=conf)


class TestModels(unittest.TestCase):
    def test_evidence_coercion_and_dict(self):
        e = Evidence(evidence_id="e1", type="ratio", metric="roe", value=25.0, unit="pct",
                     confidence=0.9)
        self.assertIs(e.type, EvidenceType.RATIO)
        d = e.to_dict()
        self.assertEqual(d["type"], "ratio")
        self.assertEqual(d["confidence"], 0.9)
        self.assertEqual(d["inputs"], [])

    def test_confidence_range_enforced(self):
        with self.assertRaises(ValueError):
            Evidence(evidence_id="x", type="document", confidence=1.5)

    def test_citation_label(self):
        c = Citation("c1", "document", title="TCS Results", section="auditors_report",
                     page=3, page_end=3)
        self.assertEqual(c.label(), "TCS Results — auditors_report — p3")
        self.assertEqual(Citation("c2", "document", document_id=7, page=4, page_end=6).label(),
                         "doc#7 — p4-6")

    def test_calculation_dict(self):
        calc = Calculation("k1", "ratio", "roe", 25.0, unit="pct",
                           expression="net_profit / total_equity * 100",
                           inputs=({"name": "net_profit", "value": 150.0, "unit": "INR",
                                    "evidence_id": "e-np"},))
        d = calc.to_dict()
        self.assertEqual(d["result"], 25.0)
        self.assertEqual(d["inputs"][0]["name"], "net_profit")

    def test_claim_status_coercion(self):
        cl = Claim("cl1", "TCS ROE was 25%", kind="numeric", value=25.0, unit="pct",
                   status="supported", confidence=0.9)
        self.assertIs(cl.status, ClaimStatus.SUPPORTED)
        self.assertTrue(cl.is_supported)
        self.assertEqual(cl.to_dict()["status"], "supported")


class TestEvidenceSet(unittest.TestCase):
    def test_dedup_keeps_higher_confidence_under_a_stable_id(self):
        ws = EvidenceSet()
        a = ws.add(_doc_ev("d1", 7, 3, "same passage text here", 0.4))
        b = ws.add(_doc_ev("d2", 7, 3, "same passage text here", 0.7))
        self.assertEqual(len(ws), 1)
        # the id handed out first stays valid; a later replacement keeps the better data
        self.assertEqual(a, b)
        self.assertEqual(ws.get("d1").confidence, 0.7)
        self.assertIsNone(ws.get("d2"))

    def test_dedup_ignores_lower_confidence_duplicate(self):
        ws = EvidenceSet()
        a = ws.add(_doc_ev("d1", 7, 3, "same passage text here", 0.7))
        b = ws.add(_doc_ev("d2", 7, 3, "same passage text here", 0.4))
        self.assertEqual(a, b)
        self.assertEqual(ws.get("d1").confidence, 0.7)

    def test_by_type_and_metric(self):
        ws = EvidenceSet()
        ws.add(_fact_ev("f1", "roe", 25.0))
        ws.add(_fact_ev("f2", "roa", 6.0))
        ws.add(_doc_ev("d1", 1, 1, "text", 0.5))
        self.assertEqual(len(ws.by_type("financial_fact")), 2)
        self.assertEqual(len(ws.documents()), 1)
        self.assertEqual(ws.by_metric("roe")[0].value, 25.0)
        self.assertEqual(len(ws.facts()), 2)

    def test_top_orders_by_confidence(self):
        ws = EvidenceSet()
        ws.add(_fact_ev("f1", "roe", 25.0, conf=0.6))
        ws.add(_fact_ev("f2", "roa", 6.0, conf=0.98))
        top = ws.top(1)
        self.assertEqual(top[0].metric, "roa")


if __name__ == "__main__":
    unittest.main()
