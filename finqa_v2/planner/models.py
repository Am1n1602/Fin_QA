"""Structured query plan (§20). Output of the planner, input to the orchestrator."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    NUMERIC_FACT = "numeric_fact"          # a single figure / ratio
    TREND = "trend"                        # change over time for one company
    COMPARISON = "comparison"              # two+ companies on a metric
    RANKING = "ranking"                    # order a set of companies
    CAUSAL = "causal"                      # why / how did X change
    CROSS_VALIDATION = "cross_validation"  # "management said X -- is it supported?"
    SEGMENT = "segment"                    # segment revenue / contribution / mix
    RESEARCH_OVERVIEW = "research_overview" # fundamental overview of a company
    UNKNOWN = "unknown"


@dataclass(slots=True)
class QueryPlan:
    question: str
    intent: Intent = Intent.UNKNOWN
    companies: list[str] = field(default_factory=list)       # NSE tickers
    periods: list[str] = field(default_factory=list)         # 'FY2026', 'FY2026Q1', 'latest', ...
    metrics: list[str] = field(default_factory=list)         # canonical metric / ratio names
    tools: list[str] = field(default_factory=list)           # Phase 8 tool names, in suggested order
    sub_questions: list[str] = field(default_factory=list)   # for decomposition (Phase 11)
    needs_documents: bool = False
    needs_calculation: bool = False
    planner: str = "rules"                                   # 'rules' | 'llm' | 'llm+repair'
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.intent = Intent(self.intent)
        # de-dup, preserve order
        for attr in ("companies", "periods", "metrics", "tools", "sub_questions"):
            setattr(self, attr, list(dict.fromkeys(getattr(self, attr))))

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "intent": self.intent.value,
            "companies": self.companies,
            "periods": self.periods,
            "metrics": self.metrics,
            "tools": self.tools,
            "sub_questions": self.sub_questions,
            "needs_documents": self.needs_documents,
            "needs_calculation": self.needs_calculation,
            "planner": self.planner,
            "notes": self.notes,
        }
