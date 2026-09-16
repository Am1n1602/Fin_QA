"""Growth math: absolute change, % change, CAGR. Negative/zero base -> % is None
(report absolute change instead), ported from v1's _compute_period_growth rule.
"""
from __future__ import annotations


def abs_change(prev, curr):
    if prev is None or curr is None:
        return None
    return curr - prev


def pct_change(prev, curr):
    if prev is None or curr is None:
        return None
    if prev <= 0:
        return None                      # % not meaningful off a zero/negative base
    return (curr - prev) / prev * 100.0


def cagr(start, end, years: float):
    """Compound annual growth rate as a percent. Requires start > 0 and years > 0."""
    if start is None or end is None or years is None:
        return None
    if start <= 0 or years <= 0 or end <= 0:
        return None
    return ((end / start) ** (1.0 / years) - 1.0) * 100.0
