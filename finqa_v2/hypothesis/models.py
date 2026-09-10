"""Hypothesis-testing data model (§22). Hypothesis states map 1:1 to ClaimStatus."""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.evidence import ClaimStatus

HypothesisStatus = ClaimStatus  # SUPPORTED / PARTIALLY_SUPPORTED / NOT_SUPPORTED / INSUFFICIENT_EVIDENCE

_DIR_VERB = {"increase": "rose", "decrease": "fell", "flat": "was roughly unchanged",
             "unknown": "changed"}

VERDICT_PHRASE = {
    ClaimStatus.SUPPORTED: "supported by both the reported numbers and management commentary",
    ClaimStatus.PARTIALLY_SUPPORTED: "consistent with the reported numbers but not confirmed by commentary",
    ClaimStatus.NOT_SUPPORTED: "contradicted by the reported numbers",
    ClaimStatus.INSUFFICIENT_EVIDENCE: "not established by the available evidence",
}

_STATUS_ORDER = (ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED,
                 ClaimStatus.INSUFFICIENT_EVIDENCE, ClaimStatus.NOT_SUPPORTED)


@dataclass(frozen=True, slots=True)
class MetricChange:
    """Steps 1-2 of §22: the target figure moved, and by how much."""

    ticker: str
    metric: str
    basis: str
    from_period: str | None
    to_period: str | None
    from_value: float | None
    to_value: float | None
    abs_change: float | None
    pct_change: float | None
    unit: str | None = None
    evidence_id: str | None = None

    @property
    def direction(self) -> str:
        d = self.abs_change
        if d is None:
            return "unknown"
        ref = abs(self.from_value) if self.from_value else None
        eps = (0.005 * ref) if ref else 1e-9
        if d > eps:
            return "increase"
        if d < -eps:
            return "decrease"
        return "flat"

    def describe(self) -> str:
        verb = _DIR_VERB.get(self.direction, "changed")
        if self.pct_change is not None:
            chg = f" by {self.pct_change:+.1f}%"
        elif self.abs_change is not None:
            chg = f" by {self.abs_change:+,.2f}"
        else:
            chg = ""
        span = f" from {self.from_period} to {self.to_period}" if self.from_period else ""
        return f"{self.ticker} {self.metric.replace('_', ' ')} {verb}{chg}{span}"

    def to_dict(self) -> dict:
        d = {k: getattr(self, k) for k in self.__slots__}
        d["direction"] = self.direction
        return d


@dataclass(slots=True)
class Hypothesis:
    """One candidate cause, its structural check, and its classification (§22 steps 4-7)."""

    hypothesis_id: str
    statement: str
    origin: str = "deterministic"           # 'deterministic' | 'llm'
    signal: tuple[str, str] | None = None   # structural basis, e.g. ('margin_bridge', 'expense_effect')
    structural_check: str = "no_data"       # 'agrees' | 'contradicts' | 'unrelated' | 'no_data'
    structural_note: str = ""
    doc_evidence_ids: list[str] = field(default_factory=list)
    support_evidence_ids: list[str] = field(default_factory=list)
    status: HypothesisStatus = ClaimStatus.INSUFFICIENT_EVIDENCE
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.status = ClaimStatus(self.status)

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "origin": self.origin,
            "signal": list(self.signal) if self.signal else None,
            "structural_check": self.structural_check,
            "structural_note": self.structural_note,
            "doc_evidence_ids": list(self.doc_evidence_ids),
            "support_evidence_ids": list(self.support_evidence_ids),
            "status": self.status.value,
            "confidence": round(self.confidence, 4),
        }


@dataclass(slots=True)
class HypothesisReport:
    """The output of one why-question run (§22 step 8 input)."""

    question: str
    change: MetricChange | None
    hypotheses: list[Hypothesis] = field(default_factory=list)
    decomposition: dict = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    @property
    def ranked(self) -> list[Hypothesis]:
        order = {s: i for i, s in enumerate(_STATUS_ORDER)}
        return sorted(self.hypotheses, key=lambda h: (order.get(h.status, 9), -h.confidence))

    @property
    def supported(self) -> list[Hypothesis]:
        return [h for h in self.hypotheses
                if h.status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED)]

    @property
    def has_confirmed_cause(self) -> bool:
        return any(h.status is ClaimStatus.SUPPORTED for h in self.hypotheses)

    def summary_text(self) -> str:
        if self.change is None:
            return "The change asked about could not be quantified, so no causes were tested."
        lines = [self.change.describe() + "."]
        if not self.hypotheses:
            lines.append("No candidate causes could be formed from the available evidence.")
            return " ".join(lines)
        for h in self.ranked:
            lines.append(f"Candidate cause — {h.statement} — is {VERDICT_PHRASE[h.status]}.")
        return " ".join(lines)

    def render(self) -> str:
        """Compact block for the reasoning-LLM prompt."""
        if self.change is None:
            return "(no measurable change to explain)"
        out = [f"TARGET CHANGE: {self.change.describe()}"]
        if self.decomposition:
            out.append("STRUCTURED DRIVERS: "
                       + "; ".join(f"{k}={v}" for k, v in self.decomposition.items()))
        out.append("CANDIDATE CAUSES (already tested against the numbers):")
        for h in self.ranked:
            note = f" — {h.structural_note}" if h.structural_note else ""
            out.append(f"  [{h.status.value}] {h.statement}{note}")
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "change": self.change.to_dict() if self.change else None,
            "hypotheses": [h.to_dict() for h in self.ranked],
            "decomposition": self.decomposition,
            "steps": list(self.steps),
            "limitations": list(self.limitations),
        }
