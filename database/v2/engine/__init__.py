"""Deterministic Financial Engine v2 (no LLM). See docs/file-guide.md."""
from __future__ import annotations

from .engine import EngineResult, FactRef, FinancialEngine
from .records import PeriodRecord, build_period_records

__all__ = [
    "EngineResult",
    "FactRef",
    "FinancialEngine",
    "PeriodRecord",
    "build_period_records",
]
