"""Deterministic arithmetic checks on a canonical record (roadmap section 10, no LLM).

Ported from data_extraction/src/extract/schema.py:validate_canonical_record, but with a
relative tolerance: filings are reported at 10^11-10^12 scale, so an absolute rupee
tolerance flags rounding noise as errors. Here a check passes when the mismatch is within
max(abs_tol, rel_tol * <largest operand>).

A failed check never drops the record -- the facts still persist, tagged with a
mapping_reason so downstream can route to review.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_ABS_TOL = 1.0        # floor: sub-rupee rounding
_REL_TOL = 5e-4       # 0.05% of the largest operand


@dataclass(frozen=True, slots=True)
class ValidationResult:
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return len(self.checks) > 0

    @property
    def failed(self) -> list[str]:
        return [k for k, ok in self.checks.items() if not ok]

    @property
    def needs_review(self) -> bool:
        return self.ran and not all(self.checks.values())


def _have(record: dict, *keys: str) -> bool:
    return all(record.get(k) is not None for k in keys)


def validate_record(record: dict, abs_tol: float = _ABS_TOL, rel_tol: float = _REL_TOL) -> ValidationResult:
    def close(lhs: float, rhs: float, *magnitude: float) -> bool:
        scale = max((abs(x) for x in magnitude), default=max(abs(lhs), abs(rhs)))
        return abs(lhs - rhs) <= max(abs_tol, rel_tol * scale)

    c: dict[str, bool] = {}

    if _have(record, "total_income", "total_expenses", "pbt_before_exceptional"):
        ti, te, pbe = record["total_income"], record["total_expenses"], record["pbt_before_exceptional"]
        c["income_minus_expenses_eq_pbt_before_exceptional"] = close(ti - te, pbe, ti, te)
    if _have(record, "pbt_before_exceptional", "exceptional_items", "pbt"):
        pbe, ex, pbt = record["pbt_before_exceptional"], record["exceptional_items"], record["pbt"]
        c["pbt_before_exceptional_plus_exceptional_eq_pbt"] = close(pbe + ex, pbt, pbe, pbt)
    if _have(record, "current_tax", "deferred_tax", "tax_expense"):
        ct, dt, tx = record["current_tax"], record["deferred_tax"], record["tax_expense"]
        c["current_plus_deferred_tax_eq_tax_expense"] = close(ct + dt, tx, ct, dt, tx)
    if _have(record, "pbt", "tax_expense"):
        pbt, tx = record["pbt"], record["tax_expense"]
        if record.get("pat_continuing_ops") is not None:
            pat = record["pat_continuing_ops"]
            c["pbt_minus_tax_eq_pat_continuing_ops"] = close(pbt - tx, pat, pbt, pat)
        elif record.get("net_profit") is not None:
            np = record["net_profit"]
            c["pbt_minus_tax_eq_net_profit"] = close(pbt - tx, np, pbt, np)
    if _have(record, "net_profit", "oci", "total_comprehensive_income"):
        np, oci, tci = record["net_profit"], record["oci"], record["total_comprehensive_income"]
        c["net_profit_plus_oci_eq_total_comprehensive_income"] = close(np + oci, tci, np, tci)
    if _have(record, "total_assets", "total_liabilities", "total_equity"):
        ta, tl, te = record["total_assets"], record["total_liabilities"], record["total_equity"]
        c["assets_eq_liabilities_plus_equity"] = close(ta, tl + te, ta, tl, te)
    if _have(record, "current_assets", "noncurrent_assets", "total_assets"):
        ca, nca, ta = record["current_assets"], record["noncurrent_assets"], record["total_assets"]
        c["current_plus_noncurrent_assets_eq_total_assets"] = close(ca + nca, ta, ca, nca, ta)
    if _have(record, "current_liabilities", "noncurrent_liabilities", "total_liabilities"):
        cl, ncl, tl = record["current_liabilities"], record["noncurrent_liabilities"], record["total_liabilities"]
        c["current_plus_noncurrent_liabilities_eq_total_liabilities"] = close(cl + ncl, tl, cl, ncl, tl)

    return ValidationResult(c)
