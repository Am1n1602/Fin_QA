"""§22 step 4: form candidate causes.

Deterministic drivers first (read straight off the decomposition, each tagged with the
structural `signal` it came from), then optional LLM-proposed causes (no signal -- they
get matched to a structural proxy at validation time). Nothing here is classified.
"""
from __future__ import annotations

import uuid

from finqa_v2.hypothesis.models import Hypothesis
from finqa_v2.hypothesis.prompt import CAUSES_SYSTEM, build_causes_prompt, parse_causes
from finqa_v2.llm import LLMBudgetExceededError, LLMError, NullProvider

_PRETTY = {
    "employee_expense": "employee / wage costs",
    "other_expenses": "other operating expenses",
    "finance_costs": "finance costs",
    "depreciation": "depreciation and amortisation",
    "tax_expense": "tax expense",
    "total_expenses": "total operating costs",
    "other_income": "other income",
    "operating_cash_flow": "operating cash flow",
}
_COST_LIKE = {"employee_expense", "other_expenses", "finance_costs", "depreciation",
              "tax_expense", "total_expenses"}
_GAP = 2.0  # pp of growth-rate gap vs revenue that counts as "meaningfully" faster/slower
_MAX_DET = 6


def _hid() -> str:
    return f"hyp-{uuid.uuid4().hex[:8]}"


def _mk(statement: str, signal=None, origin: str = "deterministic") -> Hypothesis:
    return Hypothesis(hypothesis_id=_hid(), statement=statement, signal=signal, origin=origin)


def deterministic_candidates(view) -> list[Hypothesis]:
    change = view.change
    d = change.direction
    rev = view.components.get("revenue", {}).get("pct")
    out: list[Hypothesis] = []

    # 1. net-margin bridge
    mb = view.margin_bridge or {}
    ee, re_ = mb.get("expense_effect_pp"), mb.get("revenue_effect_pp")
    if d == "decrease":
        if ee is not None and ee <= -0.2:
            out.append(_mk("Costs grew faster than revenue, compressing the margin",
                           ("margin_bridge", "expense_effect")))
        if re_ is not None and re_ <= -0.2:
            out.append(_mk("Revenue growth was too weak to cover the cost base",
                           ("margin_bridge", "revenue_effect")))
    elif d == "increase":
        if ee is not None and ee >= 0.2:
            out.append(_mk("Cost discipline widened the margin",
                           ("margin_bridge", "expense_effect")))
        if re_ is not None and re_ >= 0.2:
            out.append(_mk("Revenue growth outpaced the cost base",
                           ("margin_bridge", "revenue_effect")))

    # 2. individual cost lines vs revenue
    if rev is not None:
        for m, dd in view.components.items():
            if m in ("revenue", "net_profit") or m not in _COST_LIKE or dd.get("pct") is None:
                continue
            gap = dd["pct"] - rev
            if d == "decrease" and gap >= _GAP:
                out.append(_mk(f"Rising {_PRETTY.get(m, m)} outpaced revenue growth",
                               ("component_growth", m)))
            elif d == "increase" and gap <= -_GAP:
                out.append(_mk(f"{_PRETTY.get(m, m).capitalize()} grew more slowly than "
                               f"revenue, lifting profit", ("component_growth", m)))

    # 3. DuPont: which factor moved with ROE (and moved by a non-trivial amount)
    if view.dupont:
        want_up = d == "increase"
        best = None
        for f, dd in view.dupont.items():
            delta, frm = dd.get("delta"), dd.get("from")
            if delta is None or abs(delta) < 0.01 * abs(frm or 0) + 1e-9:
                continue
            if (delta > 0) == want_up:
                if best is None or abs(delta) > abs(view.dupont[best]["delta"]):
                    best = f
        if best:
            label = {"net_profit_margin": "a change in net profit margin",
                     "asset_turnover": "a change in asset turnover",
                     "equity_multiplier": "a change in balance-sheet leverage"}[best]
            out.append(_mk(f"The move was driven mainly by {label}", ("dupont", best)))

    # 4. segments
    if change.abs_change is not None:
        for s in view.segments:
            sp, sabs = s.get("share_pct"), s.get("abs")
            if sp is None:
                continue
            if sp >= 40:
                out.append(_mk(f"The {s['segment']} segment accounted for about "
                               f"{sp:.0f}% of the revenue change", ("segment", s["segment"])))
            elif sp <= -25:
                out.append(_mk(f"The {s['segment']} segment moved against the overall "
                               f"trend, offsetting about {abs(sp):.0f}% of the net change",
                               ("segment", s["segment"])))

    seen: set[str] = set()
    uniq: list[Hypothesis] = []
    for h in out:
        k = h.statement.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(h)
    return uniq[:_MAX_DET]


def generate_candidates(view, question: str, *, provider=None, max_total: int = 8) -> list[Hypothesis]:
    cands = deterministic_candidates(view)
    if provider is not None and not isinstance(provider, NullProvider):
        try:
            raw = provider.complete(build_causes_prompt(question, view), system=CAUSES_SYSTEM,
                                    json_object=True, temperature=0.2, max_tokens=350)
        except (LLMError, LLMBudgetExceededError):
            raw = None
        if raw:
            existing = [h.statement.lower() for h in cands]
            for phrase in parse_causes(raw):
                if _distinct(phrase.lower(), existing):
                    cands.append(_mk(phrase, None, origin="llm"))
                    existing.append(phrase.lower())
    return cands[:max_total]


def _distinct(phrase: str, existing: list[str], thresh: float = 0.6) -> bool:
    pt = set(phrase.split())
    if not pt:
        return False
    for e in existing:
        et = set(e.split())
        if et and len(pt & et) / len(pt | et) >= thresh:
            return False
    return True
