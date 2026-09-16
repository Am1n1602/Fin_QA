"""Verification data model (§25)."""
from __future__ import annotations

from dataclasses import dataclass, field

# verdicts that are NOT a failure -- either the check passed or it could not be run
_OK = {"confirmed", "recomputed", "cited", "unit_ok", "supported", "unverifiable",
       "not_recomputable", "citation_weak", "skipped"}
_HARD_FAIL = {"mismatch", "does_not_recompute", "citation_missing", "unsupported",
              "unit_mismatch"}


@dataclass(slots=True)
class ClaimCheck:
    target: str            # 'calc:<id>' | 'claim:<id>' | 'answer'
    kind: str              # 'numeric' | 'unit' | 'calculation' | 'citation' | 'support'
    verdict: str
    detail: str = ""
    text: str = ""         # claim / answer snippet the check is about

    @property
    def ok(self) -> bool:
        return self.verdict not in _HARD_FAIL

    @property
    def hard_fail(self) -> bool:
        return self.verdict in _HARD_FAIL

    def to_dict(self) -> dict:
        return {"target": self.target, "kind": self.kind, "verdict": self.verdict,
                "detail": self.detail, "text": self.text}


@dataclass(slots=True)
class VerificationReport:
    checks: list[ClaimCheck] = field(default_factory=list)
    abstained: bool = False
    adjustments: list[str] = field(default_factory=list)

    @property
    def failed(self) -> list[ClaimCheck]:
        return [c for c in self.checks if c.hard_fail]

    @property
    def status(self) -> str:
        if self.abstained:
            return "abstained"
        if self.failed or self.adjustments:
            return "passed_with_warnings"
        return "passed"

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for c in self.checks:
            out[c.verdict] = out.get(c.verdict, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "abstained": self.abstained,
            "checks": [c.to_dict() for c in self.checks],
            "counts": self.counts(),
            "adjustments": list(self.adjustments),
        }
