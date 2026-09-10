"""ClaimGraph (§24): claims linked to the evidence / calculations / citations that
support them, plus the §31 research-response view. No LLM here -- callers (the reasoning
layer, later) construct claims; this just wires and scores them.
"""
from __future__ import annotations

import uuid

from finqa_v2.evidence.confidence import claim_confidence, graph_confidence
from finqa_v2.evidence.models import Calculation, Claim, ClaimStatus, Evidence
from finqa_v2.evidence.workspace import EvidenceSet


def _cid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class ClaimGraph:
    def __init__(self, workspace: EvidenceSet | None = None):
        # explicit None check -- an empty EvidenceSet is falsy but must still be reused
        self.workspace = workspace if workspace is not None else EvidenceSet()
        self.claims: list[Claim] = []
        self._calcs: dict[str, Calculation] = {}

    # ------------------------------------------------------------------ #
    def add_calculation(self, calc: Calculation) -> str:
        self._calcs[calc.calculation_id] = calc
        return calc.calculation_id

    def add_claim(self, text: str, *, kind: str = "qualitative",
                  evidence_ids=None, calculation_ids=None,
                  value=None, unit=None,
                  status: ClaimStatus | str | None = None) -> Claim:
        ev_ids = list(evidence_ids or [])
        calc_ids = list(calculation_ids or [])
        if status is None:
            status = self._infer_status(ev_ids, calc_ids)
        support = [self.workspace.get(e).confidence for e in ev_ids if self.workspace.get(e)]
        support += [
            0.95 for c in calc_ids
            if c in self._calcs and self._calcs[c].result is not None
        ]
        claim = Claim(
            claim_id=_cid("claim"), text=text, kind=kind, value=value, unit=unit,
            evidence_ids=ev_ids, calculation_ids=calc_ids,
            status=ClaimStatus(status),
            confidence=claim_confidence(support, ClaimStatus(status)),
        )
        self.claims.append(claim)
        return claim

    def _infer_status(self, ev_ids, calc_ids) -> ClaimStatus:
        has_calc = any(c in self._calcs and self._calcs[c].result is not None for c in calc_ids)
        docs = [self.workspace.get(e) for e in ev_ids]
        docs = [d for d in docs if d is not None]
        if not docs and not has_calc:
            return ClaimStatus.INSUFFICIENT_EVIDENCE
        if has_calc and not any(d.is_document for d in docs):
            return ClaimStatus.SUPPORTED               # a deterministic calculation stands on its own
        strong = [d for d in docs if d.confidence >= 0.6]
        if strong:
            return ClaimStatus.SUPPORTED
        if docs:
            return ClaimStatus.PARTIALLY_SUPPORTED
        return ClaimStatus.SUPPORTED if has_calc else ClaimStatus.INSUFFICIENT_EVIDENCE

    # ------------------------------------------------------------------ #
    def support_for(self, claim: Claim) -> dict:
        evs = [self.workspace.get(e) for e in claim.evidence_ids]
        evs = [e for e in evs if e is not None]
        return {
            "evidence": evs,
            "calculations": [self._calcs[c] for c in claim.calculation_ids if c in self._calcs],
            "citations": [e.citation for e in evs if e.citation is not None],
        }

    def overall_confidence(self) -> float:
        return graph_confidence(
            [c.confidence for c in self.claims],
            has_not_supported=any(c.status is ClaimStatus.NOT_SUPPORTED for c in self.claims),
        )

    # ------------------------------------------------------------------ #
    def to_response(self, answer: str, *, limitations=()) -> dict:
        """The §31 internal research-response schema."""
        cited = {}
        for e in self.workspace:
            if e.citation is not None:
                cited.setdefault(e.citation.citation_id, e.citation)
        auto_lims = sorted({
            lim for e in self.workspace for lim in e.limitations
        } | {lim for c in self._calcs.values() for lim in c.limitations})
        return {
            "answer": answer,
            "confidence": round(self.overall_confidence(), 4),
            "claims": [c.to_dict() for c in self.claims],
            "calculations": [c.to_dict() for c in self._calcs.values()],
            "evidence": self.workspace.to_list(),
            "sources": [c.to_dict() for c in cited.values()],
            "limitations": list(limitations) or auto_lims,
        }
