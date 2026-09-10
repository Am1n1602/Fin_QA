"""finqa_v2 -- Fin_QA v2 Data Foundation: universe-independent models + repository
interfaces. See docs/file-guide.md."""
from __future__ import annotations

from .models import (
    Basis,
    Company,
    DocumentChunk,
    DocumentMeta,
    Exchange,
    FinancialFact,
    Index,
    IndexMembership,
    MappingConfidence,
    Segment,
    SegmentFact,
    SharePrice,
    Source,
    StatementType,
    slugify,
)

__all__ = [
    "Basis",
    "Company",
    "DocumentChunk",
    "DocumentMeta",
    "Exchange",
    "FinancialFact",
    "Index",
    "IndexMembership",
    "MappingConfidence",
    "Segment",
    "SegmentFact",
    "SharePrice",
    "Source",
    "StatementType",
    "slugify",
]
