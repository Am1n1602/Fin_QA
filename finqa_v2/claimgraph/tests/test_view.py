"""ClaimGraphView: explain / to_graph / to_mermaid / to_dict over a hand-built graph."""
from __future__ import annotations

import json
import unittest

from finqa_v2.claimgraph import ClaimGraphView
from finqa_v2.evidence.graph import ClaimGraph
from finqa_v2.evidence.models import (
    Calculation,
    Citation,
    ClaimStatus,
    Evidence,
    EvidenceType,
)
from finqa_v2.evidence.workspace import EvidenceSet


def _graph():
    ws = EvidenceSet()
    cite = Citation(citation_id="cite-doc9", kind="document", title="Q4 FY26 Results",
                    company="TCS", document_id=9, page=84, section="segment_information")
    np_ev = ws.add(Evidence(evidence_id="in-np", type=EvidenceType.FINANCIAL_FACT,
                            company="TCS", metric="net_profit", period="FY2026",
                            value=456.0, unit="INR", confidence=0.98))
    eq_ev = ws.add(Evidence(evidence_id="in-eq", type=EvidenceType.FINANCIAL_FACT,
                            company="TCS", metric="total_equity", period="FY2026",
                            value=1000.0, unit="INR", confidence=0.98))
    roe_ev = ws.add(Evidence(evidence_id="roe", type=EvidenceType.RATIO, company="TCS",
                             metric="roe", period="FY2026", value=45.6, unit="pct",
                             formula="net_profit / total_equity * 100",
                             inputs=("in-np", "in-eq"), confidence=0.9))
    doc_ev = ws.add(Evidence(evidence_id="d1", type=EvidenceType.DOCUMENT, company="TCS",
                             document_id=9, page=84, section="segment_information",
                             text="Growth was led by the IT services segment.",
                             confidence=0.6, citation=cite))

    g = ClaimGraph(ws)
    g.add_calculation(Calculation(
        calculation_id="k1", kind="ratio", name="roe", result=45.6, unit="pct",
        expression="net_profit / total_equity * 100",
        inputs=({"name": "net_profit", "value": 456.0, "unit": "INR", "evidence_id": "in-np"},
                {"name": "total_equity", "value": 1000.0, "unit": "INR", "evidence_id": "in-eq"}),
        period="FY2026"))
    g.add_claim("TCS ROE was 45.6%", kind="numeric", evidence_ids=["roe"],
                calculation_ids=["k1"], status=ClaimStatus.SUPPORTED)
    g.add_claim("Growth was driven by IT services", kind="causal", evidence_ids=["d1"],
                status=ClaimStatus.PARTIALLY_SUPPORTED)
    return g


class TestExplain(unittest.TestCase):
    def setUp(self):
        self.view = ClaimGraphView(_graph())

    def test_explain_numeric_claim(self):
        d = self.view.explain(self.view._g.claims[0])
        self.assertEqual(d["claim"]["status"], "supported")
        self.assertEqual([e["evidence_id"] for e in d["evidence"]], ["roe"])
        self.assertEqual(d["calculations"][0]["calculation_id"], "k1")
        # calc inputs are resolved to their sub-evidence
        names = {i["name"] for i in d["calculations"][0]["inputs"]}
        self.assertEqual(names, {"net_profit", "total_equity"})
        self.assertIsNotNone(d["calculations"][0]["inputs"][0]["evidence"])
        b = d["confidence_breakdown"]
        self.assertEqual(b["status_factor"], 1.0)
        self.assertGreater(b["claim_confidence"], 0.8)

    def test_explain_by_id(self):
        cid = self.view._g.claims[0].claim_id
        self.assertEqual(self.view.explain(cid)["claim"]["claim_id"], cid)

    def test_explain_causal_claim_rolls_up_source(self):
        d = self.view.explain(self.view._g.claims[1])
        self.assertEqual(d["sources"][0]["citation_id"], "cite-doc9")
        self.assertIn("p84", d["sources"][0]["label"])
        self.assertEqual(d["evidence"][0]["source"]["document_id"], 9)

    def test_render_is_text(self):
        s = self.view.render(self.view._g.claims[0])
        self.assertIn("ROE", s)
        self.assertIn("net_profit", s)


class TestGraphExport(unittest.TestCase):
    def setUp(self):
        self.view = ClaimGraphView(_graph())

    def test_node_and_edge_types(self):
        g = self.view.to_graph()
        types = {n["type"] for n in g["nodes"]}
        self.assertEqual(types, {"claim", "evidence", "calculation", "source"})
        rels = {e["rel"] for e in g["edges"]}
        self.assertTrue({"supported_by", "computed_by", "computed_from", "cites",
                         "derived_from"}.issubset(rels))

    def test_edges_reference_real_nodes(self):
        g = self.view.to_graph()
        ids = {n["id"] for n in g["nodes"]}
        for e in g["edges"]:
            self.assertIn(e["from"], ids)
            self.assertIn(e["to"], ids)

    def test_mermaid_renders(self):
        m = self.view.to_mermaid()
        self.assertTrue(m.startswith("graph TD"))
        self.assertIn("-->|supported_by|", m)
        self.assertNotIn('("(', m)          # parens inside labels were sanitised

    def test_to_dict_shape_and_json(self):
        d = self.view.to_dict()
        json.dumps(d)
        self.assertEqual(d["counts"], {"claims": 2, "evidence": 4, "calculations": 1, "sources": 1})
        self.assertEqual(len(d["claims"]), 2)
        self.assertEqual(d["sources"][0]["citation_id"], "cite-doc9")


class TestVerificationSync(unittest.TestCase):
    def test_downgraded_claim_shows_in_view(self):
        from finqa_v2.verification import Verifier

        g = _graph()
        # point the numeric claim at a dead evidence id, then verify with the graph
        g.claims[0].evidence_ids = ["ghost"]
        resp = g.to_response("x")
        Verifier().verify(resp, g.workspace, graph=g)
        d = ClaimGraphView(g).explain(g.claims[0])
        self.assertEqual(d["claim"]["status"], "not_supported")


if __name__ == "__main__":
    unittest.main()
