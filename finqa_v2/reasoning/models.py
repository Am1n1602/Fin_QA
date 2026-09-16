"""Result object for one reasoned question."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ReasoningResult:
    question: str
    plan: dict                       # QueryPlan.to_dict()
    response: dict                   # §31 schema {answer, confidence, claims, calculations, evidence, sources, limitations}
    trace: list[dict] = field(default_factory=list)   # tool-call trace
    tools_run: list[str] = field(default_factory=list)
    llm_used: bool = False
    latency_ms: float = 0.0
    hypothesis_report: dict | None = None            # §22 HypothesisReport.to_dict() for causal questions
    cross_validation_report: dict | None = None      # §23 CrossValidationReport.to_dict() for "is management right?" questions
    verification: dict | None = None                 # §25 VerificationReport.to_dict()
    claim_graph: dict | None = None                  # §24 ClaimGraphView.to_dict() -- claims -> evidence/calc/source

    @property
    def answer(self) -> str:
        return self.response.get("answer", "")

    @property
    def confidence(self) -> float:
        return self.response.get("confidence", 0.0)

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "plan": self.plan,
            "response": self.response,
            "trace": self.trace,
            "tools_run": self.tools_run,
            "llm_used": self.llm_used,
            "latency_ms": round(self.latency_ms, 1),
            "hypothesis_report": self.hypothesis_report,
            "cross_validation_report": self.cross_validation_report,
            "verification": self.verification,
            "claim_graph": self.claim_graph,
        }
