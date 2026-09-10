"""Deterministic Financial Engine v2 (no LLM). See docs/file-guide.md."""
from __future__ import annotations

from .engine import EngineResult, FactRef, FinancialEngine
from .records import PeriodRecord, build_period_records
from .segments import SegmentEngine, SegmentGrowthRow, SegmentResult, SegmentRow

__all__ = [
    "EngineResult",
    "FactRef",
    "FinancialEngine",
    "PeriodRecord",
    "SegmentEngine",
    "SegmentGrowthRow",
    "SegmentResult",
    "SegmentRow",
    "build_period_records",
]
