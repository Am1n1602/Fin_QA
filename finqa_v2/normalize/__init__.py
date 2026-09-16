"""XBRL normalization -> canonical FinancialFacts. See docs/file-guide.md."""
from __future__ import annotations

from .metrics import REGISTRY, MetricSpec, get as get_metric_spec, is_known
from .periods import PeriodInfo, normalize_period
from .pipeline import normalize_canonical_file, normalize_canonical_record
from .validate import ValidationResult, validate_record

__all__ = [
    "REGISTRY",
    "MetricSpec",
    "PeriodInfo",
    "ValidationResult",
    "get_metric_spec",
    "is_known",
    "normalize_canonical_file",
    "normalize_canonical_record",
    "normalize_period",
    "validate_record",
]
