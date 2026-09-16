"""Cross-validation data model (§23). Verdicts map 1:1 to ClaimStatus."""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.evidence import ClaimStatus

CrossCheckStatus = ClaimStatus

_STATUS_VERDICT = {
    ClaimStatus.SUPPORTED: "supported by the reported financials",
    ClaimStatus.PARTIALLY_SUPPORTED: "partially supported",
    ClaimStatus.NOT_SUPPORTED: "not supported by the reported financials",
    ClaimStatus.INSUFFICIENT_EVIDENCE: "not verifiable from the available evidence",
}


@dataclass(frozen=True, slots=True)
class ManagementClaim:
    """The checkable assertion pulled out of the question / a supplied statement."""

    raw: str
    kind: str                       # growth_driver | margin_move | segment_strength | magnitude | directional | generic
    subject: str | None = None      # canonical metric the claim is about
    direction: str | None = None    # 'increase' | 'decrease'
    mechanism: str | None = None    # 'volume' | 'pricing' | 'demand' | 'cost_control' | 'mix' | 'acquisition' | <segment phrase>
    mechanism_kind: str = "generic" # 'volume_pricing' | 'demand' | 'cost' | 'mix' | 'segment' | 'generic'
    claimed_value: float | None = None
    claimed_unit: str | None = None  # 'pct' | 'pp' | 'INR'
    period: str | None = None
    origin: str = "rules"           # 'rules' | 'rules+llm'

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(slots=True)
class CrossCheck:
    """One structured test of the claim against the numbers."""

    name: str                       # directional | magnitude | segment_attribution | margin_bridge | mechanism
    verdict: str                    # 'agrees' | 'contradicts' | 'unrelated' | 'no_data'
    detail: str = ""
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "verdict": self.verdict, "detail": self.detail,
                "evidence_ids": list(self.evidence_ids)}


@dataclass(slots=True)
class CrossValidationReport:
    question: str
    company: str | None
    claim: ManagementClaim | None
    checks: list[CrossCheck] = field(default_factory=list)
    doc_status: str = "absent"      # 'stated' | 'absent' | 'contradicted'
    doc_evidence_ids: list[str] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.INSUFFICIENT_EVIDENCE
    confidence: float = 0.0
    steps: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    support_evidence_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = ClaimStatus(self.status)

    # ---- views for the reasoning layer ----
    def render(self) -> str:
        if self.claim is None:
            return "(no checkable management claim was identified)"
        out = [f"MANAGEMENT CLAIM: \"{self.claim.raw}\"",
               f"  parsed as: kind={self.claim.kind} subject={self.claim.subject} "
               f"direction={self.claim.direction} mechanism={self.claim.mechanism}"]
        out.append("STRUCTURED CHECKS:")
        for c in self.checks:
            out.append(f"  [{c.verdict}] {c.name}: {c.detail}")
        out.append(f"FILING TEXT: management statement is {self.doc_status} in the retrieved passages")
        out.append(f"CROSS-VALIDATION: {self.status.value}")
        return "\n".join(out)

    def answer_sentences(self) -> list[str]:
        if self.claim is None:
            return ["No checkable management claim could be identified in the question."]
        lines = [f'The claim that {self.claim.raw!r} is {_STATUS_VERDICT[self.status]}.']
        for c in self.checks:
            if c.verdict in ("agrees", "contradicts"):
                verb = "supports" if c.verdict == "agrees" else "runs against"
                lines.append(f"The {c.name.replace('_', ' ')} check {verb} it "
                             f"({c.detail.rstrip('.')}).")
        if self.doc_status == "stated":
            lines.append("A filing passage stating this was retrieved.")
        elif self.doc_status == "contradicted":
            lines.append("A filing passage appears to contradict it.")
        else:
            lines.append("No filing passage stating this was retrieved.")
        return lines

    def answer_limitations(self) -> list[str]:
        lims = list(self.limitations)
        lims.append("Assessment produced by deterministic cross-validation; no LLM synthesis was run.")
        return lims

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "company": self.company,
            "claim": self.claim.to_dict() if self.claim else None,
            "checks": [c.to_dict() for c in self.checks],
            "doc_status": self.doc_status,
            "doc_evidence_ids": list(self.doc_evidence_ids),
            "status": self.status.value,
            "confidence": round(self.confidence, 4),
            "steps": list(self.steps),
            "limitations": list(self.limitations),
            "support_evidence_ids": list(self.support_evidence_ids),
        }
