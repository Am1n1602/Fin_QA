"""Derived quantities that aren't single XBRL tags. Ported verbatim (formula-wise)
from data_analysis/src/analysis/ratios.py -- these were cross-validated against
external sources in v1.

Convention (from v1): borrowings absent on a record -> 0 (genuinely debt-free
companies have no borrowings tag at all). Cash absent -> None, never 0.
"""
from __future__ import annotations

from typing import Mapping

Rec = Mapping[str, float]


def _g(rec: Rec, key: str):
    return rec.get(key)


def ebit(rec: Rec):
    """PBT before exceptional items + finance costs."""
    pbe = _g(rec, "pbt_before_exceptional")
    if pbe is None:
        return None
    return pbe + (_g(rec, "finance_costs") or 0)


def operating_ebit(rec: Rec):
    """Revenue - employee - depreciation - other expenses (excludes other income)."""
    parts = [_g(rec, k) for k in ("revenue", "employee_expense", "depreciation", "other_expenses")]
    if any(p is None for p in parts):
        return None
    rev, emp, dep, oth = parts
    return rev - emp - dep - oth


def ebitda(rec: Rec):
    """PBT before exceptional + depreciation + finance costs - other income."""
    pbe = _g(rec, "pbt_before_exceptional")
    dep = _g(rec, "depreciation")
    oi = _g(rec, "other_income")
    if None in (pbe, dep, oi):
        return None
    return pbe + dep + (_g(rec, "finance_costs") or 0) - oi


def total_debt(rec: Rec) -> float:
    return (
        (_g(rec, "borrowings_current") or 0)
        + (_g(rec, "borrowings_noncurrent") or 0)
        + (_g(rec, "debt_securities") or 0)
        + (_g(rec, "deposits_debt") or 0)
    )


def net_debt(rec: Rec):
    cash = _g(rec, "cash_and_equivalents")
    if cash is None:
        return None
    return total_debt(rec) - cash


def capex(rec: Rec):
    ppe = _g(rec, "capex_ppe")
    intang = _g(rec, "capex_intangibles")
    if ppe is None and intang is None:
        return None
    return (ppe or 0) + (intang or 0)


def shares_outstanding(rec: Rec):
    puc = _g(rec, "paid_up_equity_capital")
    fv = _g(rec, "face_value_per_share")
    if puc is None or not fv:
        return None
    return puc / fv


DERIVED_UNITS = {
    "ebit": "INR", "operating_ebit": "INR", "ebitda": "INR",
    "total_debt": "INR", "net_debt": "INR", "capex": "INR",
    "shares_outstanding": "shares",
}

DERIVED = {
    "ebit": ebit,
    "operating_ebit": operating_ebit,
    "ebitda": ebitda,
    "total_debt": total_debt,
    "net_debt": net_debt,
    "capex": capex,
    "shares_outstanding": shares_outstanding,
}
