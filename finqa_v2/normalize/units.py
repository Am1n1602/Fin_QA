"""Unit normalization.

For canonical-JSON input the authoritative unit is the metric registry (the raw XBRL
unitRef was already dropped upstream). `measure_to_unit` + `apply_sign` are for the
future raw-fact ingestion path, which still has unitRef / decimals / sign.
"""
from __future__ import annotations

from finqa_v2.normalize import metrics


def unit_for(metric_name: str) -> str | None:
    spec = metrics.get(metric_name)
    return spec.unit if spec else None


def currency_for(metric_name: str) -> str | None:
    """Only INR-denominated amounts carry a currency; ratios / per-share / share
    counts do not."""
    u = unit_for(metric_name)
    return "INR" if u == "INR" else None


def measure_to_unit(xbrl_measure: str | None) -> str | None:
    """Map an XBRL unit measure string to this project's unit vocabulary.
    e.g. 'iso4217:INR' -> 'INR', 'xbrli:shares' -> 'shares',
         'iso4217:INR/xbrli:shares' -> 'per_share', 'xbrli:pure' -> 'x'.
    """
    if not xbrl_measure:
        return None
    m = xbrl_measure.strip().lower()
    if "/" in m and "shares" in m and ("inr" in m or "iso4217" in m):
        return "per_share"
    if "shares" in m:
        return "shares"
    if "inr" in m or "iso4217" in m:
        return "INR"
    if "pure" in m:
        return "x"
    return None


def apply_sign(value: float | None, sign: str | None) -> float | None:
    if value is None:
        return None
    return -value if sign == "-" else value


def reconcile(metric_name: str, xbrl_measure: str | None) -> tuple[str | None, str | None]:
    """Return (unit, note). Registry wins; note is set when the XBRL measure disagrees."""
    registry_unit = unit_for(metric_name)
    measured = measure_to_unit(xbrl_measure)
    if registry_unit and measured and registry_unit != measured:
        return registry_unit, f"unit mismatch: registry={registry_unit!r} xbrl={measured!r} ({xbrl_measure!r})"
    return (registry_unit or measured), None
