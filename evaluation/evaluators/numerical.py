"""Numeric answer scoring (§39): exact match + tolerance-based accuracy. See docs/file-guide.md."""
from __future__ import annotations

import re
from typing import Any

# scale words the deterministic / LLM synthesizer may emit
_SCALE = {
    "lakh crore": 1e12, "lakh crores": 1e12,
    "crore": 1e7, "crores": 1e7, "cr": 1e7,
    "lakh": 1e5, "lakhs": 1e5,
    "billion": 1e9, "bn": 1e9,
    "million": 1e6, "mn": 1e6,
    "trillion": 1e12,
}
_NUM = r"[-+]?\d[\d,]*(?:\.\d+)?"
_PCT_RE = re.compile(rf"({_NUM})\s*(?:%|percent|pct|pp|percentage points?)", re.I)
_X_RE = re.compile(rf"({_NUM})\s*(?:x\b|times\b)", re.I)
_SCALED_RE = re.compile(rf"(?:₹|rs\.?|inr)?\s*({_NUM})\s*(lakh crores?|crores?|cr\b|lakhs?|billion|bn\b|million|mn\b|trillion)", re.I)
_INR_RE = re.compile(rf"(?:₹|rs\.?|inr)\s*({_NUM})|({_NUM})\s*(?:inr|rupees)", re.I)
_BARE_RE = re.compile(_NUM)


def _f(s: str) -> float | None:
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def extract_figures(text: str, family: str) -> list[float]:
    """All figures in `text` belonging to a unit family: 'pct' | 'x' | 'inr'."""
    text = text or ""
    out: list[float] = []
    if family == "pct":
        out = [v for m in _PCT_RE.finditer(text) if (v := _f(m.group(1))) is not None]
    elif family == "x":
        out = [v for m in _X_RE.finditer(text) if (v := _f(m.group(1))) is not None]
    elif family == "inr":
        for m in _SCALED_RE.finditer(text):
            v = _f(m.group(1))
            if v is not None:
                out.append(v * _SCALE.get(m.group(2).lower().rstrip("."), 1.0))
        for m in _INR_RE.finditer(text):
            v = _f(m.group(1) or m.group(2))
            if v is not None:
                out.append(v)
        if not out:  # bare grouped numbers, last resort
            out = [v for m in _BARE_RE.finditer(text)
                   if (v := _f(m.group(0))) is not None and abs(v) >= 1000]
    return out


def unit_family(unit: str | None) -> str:
    u = (unit or "").strip().lower()
    if u in ("%", "pct", "pp", "percent"):
        return "pct"
    if u in ("x", "ratio", "times"):
        return "x"
    return "inr"


class NumericalEvaluator:
    name = "numerical"

    def __init__(self, default_tolerance_pct: float = 1.0) -> None:
        self.default_tolerance_pct = default_tolerance_pct

    def score(self, record: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        ref = record.get("reference_value")
        if record.get("answer_type") != "numeric" or ref is None:
            return {"metrics": {}, "verdict": "na", "detail": "no numeric reference"}

        answer = (result.get("response") or result).get("answer", "") if isinstance(result, dict) else ""
        family = unit_family(record.get("reference_unit"))
        figs = extract_figures(answer, family)
        tol_pct = record.get("tolerance_pct")
        tol_pct = self.default_tolerance_pct if tol_pct is None else tol_pct
        denom = abs(ref) if ref else 1.0
        tol = max(denom * tol_pct / 100.0, 1e-9)

        best = min((abs(v - ref) for v in figs), default=None)
        within_tol = best is not None and best <= tol
        exact = best is not None and (best <= max(denom * 5e-4, 0.01))
        return {
            "metrics": {
                "reference_value": ref,
                "figures_found": figs,
                "closest_abs_error": None if best is None else round(best, 6),
                "rel_error_pct": None if best is None else round(100.0 * best / denom, 4),
                "within_tolerance": within_tol,
                "exact_match": exact,
            },
            "verdict": "pass" if within_tol else "fail",
            "detail": (f"no figure in the '{family}' family found in the answer"
                       if best is None else
                       f"closest {('matches' if within_tol else 'differs')} "
                       f"(rel err {100.0 * best / denom:.3f}%, tol {tol_pct}%)"),
        }
