"""Ratio reconciliation (roadmap Phase 3, §13): reported vs. computed ratios.
See docs/file-guide.md."""
from __future__ import annotations

from .reconcile import find_ratio_comparisons

__all__ = ["find_ratio_comparisons"]
