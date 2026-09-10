"""Standardized evidence objects (§18). Raw engine / retrieval output is adapted into
these before it ever reaches the reasoning layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvidenceType(str, Enum):
    FINANCIAL_FACT = "financial_fact"   # a canonical figure from the Financial Data Layer
    RATIO = "ratio"                     # a computed ratio (ROE, margins, ...)
    GROWTH = "growth"                   # YoY / QoQ / CAGR
    SEGMENT = "segment"                 # segment-level revenue / contribution
    DOCUMENT = "document"               # a retrieved passage from a filing
    CALCULATION = "calculation"         # the output of an explicit calculation


class ClaimStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True, slots=True)
class Citation:
    """Rendered provenance for a piece of evidence. Maps back to a DB `sources` row."""

    citation_id: str
    kind: str                       # 'document' | 'filing' | 'index'
    title: str | None = None
    company: str | None = None
    document_id: int | None = None
    page: int | None = None
    page_end: int | None = None
    section: str | None = None
    uri: str | None = None
    period: str | None = None
    source_id: int | None = None

    def label(self) -> str:
        parts = [self.title or (f"doc#{self.document_id}" if self.document_id else self.kind)]
        if self.section:
            parts.append(self.section)
        if self.page is not None:
            parts.append(f"p{self.page}" if self.page == (self.page_end or self.page)
                         else f"p{self.page}-{self.page_end}")
        return " — ".join(str(p) for p in parts)

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


@dataclass(frozen=True, slots=True)
class Evidence:
    """One normalized unit of support (§18)."""

    evidence_id: str
    type: EvidenceType
    text: str | None = None            # passage text, or a rendered statement of the fact
    company: str | None = None
    company_id: int | None = None
    metric: str | None = None
    period: str | None = None
    value: float | None = None
    unit: str | None = None
    document_id: int | None = None
    page: int | None = None
    section: str | None = None
    retrieval_score: float | None = None
    confidence: float = 0.0            # 0..1
    citation: Citation | None = None
    formula: str | None = None
    inputs: tuple[str, ...] = ()       # evidence_ids this one derives from (calculations)
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", EvidenceType(self.type))
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence out of range: {self.confidence}")

    @property
    def is_document(self) -> bool:
        return self.type is EvidenceType.DOCUMENT

    @classmethod
    def from_dict(cls, d: dict) -> "Evidence":
        cit = d.get("citation")
        return cls(
            evidence_id=d["evidence_id"], type=d["type"], text=d.get("text"),
            company=d.get("company"), company_id=d.get("company_id"),
            metric=d.get("metric"), period=d.get("period"), value=d.get("value"),
            unit=d.get("unit"), document_id=d.get("document_id"), page=d.get("page"),
            section=d.get("section"), retrieval_score=d.get("retrieval_score"),
            confidence=d.get("confidence", 0.0),
            citation=Citation(**cit) if isinstance(cit, dict) else None,
            formula=d.get("formula"), inputs=tuple(d.get("inputs", ())),
            limitations=tuple(d.get("limitations", ())),
        )

    def to_dict(self) -> dict:
        return {
            "evidence_id": self.evidence_id,
            "type": self.type.value,
            "text": self.text,
            "company": self.company,
            "company_id": self.company_id,
            "metric": self.metric,
            "period": self.period,
            "value": self.value,
            "unit": self.unit,
            "document_id": self.document_id,
            "page": self.page,
            "section": self.section,
            "retrieval_score": self.retrieval_score,
            "confidence": round(self.confidence, 4),
            "citation": self.citation.to_dict() if self.citation else None,
            "formula": self.formula,
            "inputs": list(self.inputs),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class Calculation:
    """A deterministic computation, with its inputs pinned to evidence."""

    calculation_id: str
    kind: str                          # 'metric' | 'ratio' | 'growth' | 'cagr' | 'decomposition' | 'arithmetic'
    name: str
    result: float | None
    unit: str | None = None
    expression: str | None = None
    inputs: tuple[dict, ...] = ()      # ({name, value, unit, evidence_id}, ...)
    period: str | None = None
    limitations: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict) -> "Calculation":
        return cls(
            calculation_id=d["calculation_id"], kind=d["kind"], name=d["name"],
            result=d.get("result"), unit=d.get("unit"), expression=d.get("expression"),
            inputs=tuple(dict(i) for i in d.get("inputs", ())),
            period=d.get("period"), limitations=tuple(d.get("limitations", ())),
        )

    def to_dict(self) -> dict:
        return {
            "calculation_id": self.calculation_id,
            "kind": self.kind,
            "name": self.name,
            "result": self.result,
            "unit": self.unit,
            "expression": self.expression,
            "inputs": [dict(i) for i in self.inputs],
            "period": self.period,
            "limitations": list(self.limitations),
        }


@dataclass(slots=True)
class Claim:
    """A single assertion the answer makes -- the unit the Verifier checks (§25)."""

    claim_id: str
    text: str
    kind: str = "qualitative"          # 'numeric' | 'causal' | 'comparative' | 'trend' | 'qualitative'
    value: float | None = None
    unit: str | None = None
    evidence_ids: list[str] = field(default_factory=list)
    calculation_ids: list[str] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.INSUFFICIENT_EVIDENCE
    confidence: float = 0.0

    def __post_init__(self) -> None:
        self.status = ClaimStatus(self.status)

    @property
    def is_supported(self) -> bool:
        return self.status in (ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED)

    def to_dict(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "kind": self.kind,
            "value": self.value,
            "unit": self.unit,
            "evidence_ids": list(self.evidence_ids),
            "calculation_ids": list(self.calculation_ids),
            "status": self.status.value,
            "confidence": round(self.confidence, 4),
        }
