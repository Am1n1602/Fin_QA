"""Evidence Layer (§18/§24/§31): the common interface between engine, retrieval,
calculator, reasoning and verification. See docs/file-guide.md."""
from __future__ import annotations

from .build import (
    citation_for_document,
    evidence_from_engine_result,
    evidence_from_retrieved_chunk,
    evidence_from_segment_result,
)
from .graph import ClaimGraph
from .models import (
    Calculation,
    Citation,
    Claim,
    ClaimStatus,
    Evidence,
    EvidenceType,
)
from .workspace import EvidenceSet

__all__ = [
    "Calculation",
    "Citation",
    "Claim",
    "ClaimGraph",
    "ClaimStatus",
    "Evidence",
    "EvidenceSet",
    "EvidenceType",
    "citation_for_document",
    "evidence_from_engine_result",
    "evidence_from_retrieved_chunk",
    "evidence_from_segment_result",
]
