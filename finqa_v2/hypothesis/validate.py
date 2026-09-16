"""§22 steps 6-7: check each candidate cause against the structured numbers, then
classify it into one of the four hypothesis states.

`structural_check` re-reads the decomposition signal the hypothesis rests on (for
LLM-proposed causes, a keyword map picks the nearest structured proxy) and returns
one of: agrees / contradicts / unrelated / no_data. `classify` combines that verdict
with whether any retrieved filing passage backs the cause.
"""
from __future__ import annotations

from finqa_v2.evidence import ClaimStatus
from finqa_v2.retrieval.tokenize import tokenize

AGREES, CONTRADICTS, UNRELATED, NO_DATA = "agrees", "contradicts", "unrelated", "no_data"

_DOC_CONF_MIN = 0.45

# keyword -> structural signal, for LLM causes that carry no signal of their own
_KEYWORDS: list[tuple[tuple[str, ...], tuple[str, str]]] = [
    (("wage", "salary", "salaries", "employee", "headcount", "compensation", "attrition", "hiring"),
     ("component_growth", "employee_expense")),
    (("interest cost", "finance cost", "borrowing cost", "debt servicing", "higher debt"),
     ("component_growth", "finance_costs")),
    (("tax", "effective tax"), ("component_growth", "tax_expense")),
    (("depreciation", "amortis", "amortiz"), ("component_growth", "depreciation")),
    (("raw material", "input cost", "commodity", "material cost", "overhead", "opex", "sg&a"),
     ("component_growth", "other_expenses")),
    (("cost", "expense", "cost base"), ("margin_bridge", "expense_effect")),
    (("revenue", "sales", "demand", "volume", "pricing", "price", "topline", "top-line",
      "billing", "order book"), ("margin_bridge", "revenue_effect")),
]

_BASE_CONF = {
    ClaimStatus.SUPPORTED: 0.82,
    ClaimStatus.PARTIALLY_SUPPORTED: 0.52,
    ClaimStatus.NOT_SUPPORTED: 0.20,
    ClaimStatus.INSUFFICIENT_EVIDENCE: 0.12,
}

_RISING = ("rising", "rose", "higher", "outpaced", "grew faster", "faster than", "increase")
_SLOWER = ("slower", "more slowly", "lower", "contained", "controlled", "discipline",
           "fell", "declined", "outpaced revenue")


def _match_signal(statement: str) -> tuple[str, str] | None:
    s = statement.lower()
    for kws, sig in _KEYWORDS:
        if any(k in s for k in kws):
            return sig
    return None


def structural_check(hyp, view) -> tuple[str, str]:
    sig = hyp.signal or _match_signal(hyp.statement)
    if sig is None:
        return NO_DATA, "no structured proxy for this cause"
    kind, key = sig
    up = view.change.direction == "increase"

    if kind == "margin_bridge":
        val = (view.margin_bridge or {}).get(f"{key}_pp")
        if val is None:
            return NO_DATA, "net-margin bridge unavailable"
        if abs(val) < 0.1:
            return UNRELATED, f"{key} contributed only {val:+.2f} pp"
        helps = val > 0
        if helps == up:
            return AGREES, f"{key} = {val:+.2f} pp, in the direction of the change"
        return CONTRADICTS, f"{key} = {val:+.2f} pp, against the direction of the change"

    if kind == "component_growth":
        comp = view.components.get(key)
        rev = view.components.get("revenue", {}).get("pct")
        if not comp or comp.get("pct") is None or rev is None:
            return NO_DATA, f"{key} growth unavailable"
        gap = comp["pct"] - rev
        s = hyp.statement.lower()
        says_rising = any(w in s for w in _RISING)
        says_slower = any(w in s for w in _SLOWER)
        if not up:  # target fell -> a cost rising faster than revenue hurts
            if gap >= _min_gap():
                return AGREES, f"{key} grew {gap:+.1f} pp faster than revenue"
            if gap <= -_min_gap() and says_rising:
                return CONTRADICTS, f"{key} grew {gap:+.1f} pp slower than revenue, not faster"
            return UNRELATED, f"{key} grew roughly in line with revenue ({gap:+.1f} pp)"
        if gap <= -_min_gap():
            return AGREES, f"{key} grew {gap:+.1f} pp slower than revenue"
        if gap >= _min_gap() and says_slower:
            return CONTRADICTS, f"{key} grew {gap:+.1f} pp faster than revenue, not slower"
        return UNRELATED, f"{key} grew roughly in line with revenue ({gap:+.1f} pp)"

    if kind == "dupont":
        dd = (view.dupont or {}).get(key)
        if not dd or dd.get("delta") is None:
            return NO_DATA, "DuPont factor unavailable"
        delta = dd["delta"]
        if abs(delta) < 1e-6:
            return UNRELATED, f"{key} barely moved (delta {delta:+.3f})"
        aligned = (delta > 0) == up
        return (AGREES if aligned else CONTRADICTS), f"{key} delta {delta:+.3f}"

    if kind == "segment":
        seg = next((s for s in view.segments if s["segment"] == key), None)
        if not seg or seg.get("share_pct") is None:
            return NO_DATA, "segment share unavailable"
        sp = seg["share_pct"]
        if abs(sp) >= 25:
            return AGREES, f"{key} was {sp:.0f}% of the total revenue change"
        return UNRELATED, f"{key} was only {sp:.0f}% of the total revenue change"

    return NO_DATA, ""


def _min_gap() -> float:
    return 2.0


def classify(hyp, doc_confidences) -> tuple[ClaimStatus, float]:
    docs = [c for c in doc_confidences if c is not None]
    has_docs = any(c >= _DOC_CONF_MIN for c in docs)
    sc = hyp.structural_check
    if sc == CONTRADICTS:
        status = ClaimStatus.NOT_SUPPORTED
    elif sc == AGREES and has_docs:
        status = ClaimStatus.SUPPORTED
    elif sc == AGREES:
        status = ClaimStatus.PARTIALLY_SUPPORTED
    elif has_docs:
        status = ClaimStatus.PARTIALLY_SUPPORTED
    else:
        status = ClaimStatus.INSUFFICIENT_EVIDENCE
    conf = _BASE_CONF[status]
    if docs:
        conf = min(0.95, conf + 0.10 * (sum(docs) / len(docs)))
    return status, round(conf, 4)


def lexical_overlap(statement: str, text: str) -> int:
    return len(set(tokenize(statement)) & set(tokenize(text or "")))
