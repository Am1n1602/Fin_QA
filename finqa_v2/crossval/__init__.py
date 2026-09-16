"""Cross-Validation Engine (§23): check a management statement against the financials,
the segment data and the filing text. See docs/file-guide.md."""
from __future__ import annotations

from .models import (
    CrossCheck,
    CrossValidationReport,
    ManagementClaim,
)
from .validator import CrossValidator

__all__ = [
    "CrossValidator",
    "CrossCheck",
    "CrossValidationReport",
    "ManagementClaim",
]
