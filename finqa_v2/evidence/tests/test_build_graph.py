"""Adapters (engine / retrieval / segment -> Evidence) and ClaimGraph / §31 response."""
from __future__ import annotations

import unittest

from finqa_v2.engine.engine import EngineResult, FactRef
from finqa_v2.engine.segments import SegmentGrowthRow, SegmentResult, SegmentRow
from finqa_v2.evidence.build import (
    evidence_from_engine_result,
    evidence_from_retrieved_chunk,
    evidence_from_segment_result,
)
from finqa_v2.evidence.graph import ClaimGraph
from finqa_v2.evidence.models import ClaimStatus, EvidenceType
from finqa_v2.evidence.workspace import EvidenceSet
from finqa_v2.models import DocumentChunk
from finqa_v2.retrieval.retriever import RetrievedChunk

_ENG = EngineResult(
    kind="ratio", name="roe", value=25.0, unit="pct", company="TCS", basis="consolidated",
    period="FY2026", formula="net_profit / total_equity * 100",
    inputs=(FactRef("net_profit", 150.0, "FY2026", 11), FactRef("total_equity", 600.0, "FY2026", 12)),
)
_ENG_FLAGGED = EngineResult(
    kind="ratio", name="roce", value=10.0, unit="pct", company="HDFCBANK", basis="consolidated",
    period="FY2026", formula="ebit / (total_assets - current_liabilities) * 100",
    inputs=(FactRef("total_assets", 1e12, "FY2026", 1),),
    limitations=("total_assets: source record flagged for review (current+noncurrent mismatch)",),
)


class TestEngineAdapter(unittest.TestCase):
    def test_result_and_calculation(self):
        ws = EvidenceSet()
        ev, calc = evidence_from_engine_result(_ENG, workspace=ws)
        self.assertIs(ev.type, EvidenceType.RATIO)
        self.assertEqual(ev.value, 25.0)
        self.assertEqual(ev.formula, _ENG.formula)
        self.assertEqual(len(ev.inputs), 2)                       # two sub-evidence
        self.assertEqual(len(ws.by_type("financial_fact")), 2)    # inputs added to workspace
        self.assertEqual(calc.result, 25.0)
        self.assertEqual(calc.inputs[0]["name"], "net_profit")
        self.assertEqual(calc.inputs[0]["unit"], "INR")
        self.assertGreater(ev.confidence, 0.85)

    def test_flagged_lowers_confidence(self):
        ws = EvidenceSet()
        ev, _ = evidence_from_engine_result(_ENG_FLAGGED, workspace=ws)
        self.assertLess(ev.confidence, 0.85)
        self.assertLessEqual(ws.by_type("financial_fact")[0].confidence, 0.75)


class TestRetrievalAdapter(unittest.TestCase):
    def test_chunk_to_document_evidence(self):
        ch = DocumentChunk(document_id=5, company_id=3, chunk_index=0,
                           text="Independent Auditor's Report. Basis for Opinion.",
                           page_start=2, page_end=2, section="auditors_report",
                           financial_year=2026, document_type="results_pdf", topic="prose")
        hit = RetrievedChunk(chunk=ch, rank=1, scores={"lexical": 6.0, "rrf": None, "rerank": None})
        ev = evidence_from_retrieved_chunk(hit, company="RELIANCE")
        self.assertIs(ev.type, EvidenceType.DOCUMENT)
        self.assertEqual(ev.page, 2)
        self.assertEqual(ev.section, "auditors_report")
        self.assertEqual(ev.period, "FY2026")
        self.assertGreaterEqual(ev.confidence, 0.30)
        self.assertLessEqual(ev.confidence, 0.85)


class TestSegmentAdapter(unittest.TestCase):
    def test_level_and_growth_rows(self):
        level = SegmentResult("segment_data", "RELIANCE", "consolidated", "FY2026",
                              (SegmentRow("Retail", 3710.0, 28.2, "FY2026"),
                               SegmentRow("O2C", 6624.0, 50.4, "FY2026")),
                              total_revenue=13140.0)
        evs = evidence_from_segment_result(level)
        self.assertEqual(len(evs), 2)
        self.assertTrue(all(e.type is EvidenceType.SEGMENT for e in evs))
        self.assertIn("28.2% of total", evs[0].text)

        growth = SegmentResult("segment_growth", "RELIANCE", "consolidated", "prev -> curr",
                               (SegmentGrowthRow("Retail", 3300.0, 3700.0, 400.0, 12.1, 33.0),),
                               total_change=1200.0)
        gev = evidence_from_segment_result(growth)
        self.assertIn("+33% of the total change", gev[0].text)
        self.assertEqual(gev[0].value, 400.0)


class TestClaimGraph(unittest.TestCase):
    def _graph_with_roe(self):
        g = ClaimGraph()
        ev, calc = evidence_from_engine_result(_ENG, workspace=g.workspace)
        g.add_calculation(calc)
        return g, ev, calc

    def test_calc_backed_claim_is_supported(self):
        g, ev, calc = self._graph_with_roe()
        claim = g.add_claim("TCS ROE in FY2026 was 25.0%", kind="numeric", value=25.0, unit="pct",
                            evidence_ids=[ev.evidence_id], calculation_ids=[calc.calculation_id])
        self.assertIs(claim.status, ClaimStatus.SUPPORTED)
        self.assertGreater(claim.confidence, 0.7)
        sup = g.support_for(claim)
        self.assertEqual(len(sup["calculations"]), 1)

    def test_unsupported_claim(self):
        g = ClaimGraph()
        claim = g.add_claim("Margins fell because of competition", kind="causal")
        self.assertIs(claim.status, ClaimStatus.INSUFFICIENT_EVIDENCE)
        self.assertLess(claim.confidence, 0.2)

    def test_to_response_schema(self):
        g, ev, calc = self._graph_with_roe()
        # add a weak document evidence + a partially-supported causal claim
        ch = DocumentChunk(document_id=9, company_id=3, chunk_index=0,
                           text="Management noted pricing pressure in some accounts.",
                           page_start=4, page_end=4, section="notes", financial_year=2026,
                           document_type="results_pdf", topic="prose")
        dev = evidence_from_retrieved_chunk(
            RetrievedChunk(ch, 5, {"lexical": 1.0, "rrf": None, "rerank": None}),
            company="TCS", workspace=g.workspace)
        g.add_claim("TCS ROE in FY2026 was 25.0%", kind="numeric",
                    evidence_ids=[ev.evidence_id], calculation_ids=[calc.calculation_id])
        g.add_claim("Some margin pressure was noted", kind="causal", evidence_ids=[dev.evidence_id])

        resp = g.to_response("TCS ROE was 25.0% in FY2026; some margin pressure was noted.")
        self.assertEqual(set(resp), {"answer", "confidence", "claims", "calculations",
                                     "evidence", "sources", "limitations"})
        self.assertEqual(len(resp["claims"]), 2)
        self.assertEqual(len(resp["calculations"]), 1)
        self.assertTrue(0.0 <= resp["confidence"] <= 1.0)
        self.assertGreater(len(resp["evidence"]), 2)


if __name__ == "__main__":
    unittest.main()
