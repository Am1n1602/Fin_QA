"""§23 steps 2-3: test the management claim against structured financials + segment data.

Reuses the Phase 11 machinery: `detect_metric_change` quantifies the subject metric and
`build_decomposition` gives the component / margin-bridge / segment drivers the checks
read. A mechanism with no structured proxy (volumes, pricing, demand) yields `no_data` --
never a fabricated confirmation (§9/§23).
"""
from __future__ import annotations

import re

from finqa_v2.crossval.models import CrossCheck
from finqa_v2.hypothesis.decompose import build_decomposition
from finqa_v2.hypothesis.detect import detect_metric_change
from finqa_v2.retrieval.tokenize import tokenize

AGREES, CONTRADICTS, UNRELATED, NO_DATA = "agrees", "contradicts", "unrelated", "no_data"

_DIR_ALIGN = {"increase": "increase", "decrease": "decrease"}


def run_structured_checks(engine, ticker, claim, *, basis="consolidated", workspace=None):
    """-> (list[CrossCheck], DecompositionView | None, MetricChange | None)."""
    checks: list[CrossCheck] = []
    subject = claim.subject or "revenue"
    change = detect_metric_change(engine, ticker, subject, basis=basis, workspace=workspace)
    if change is None:
        checks.append(CrossCheck("directional", NO_DATA,
                                 f"no usable series for {subject.replace('_', ' ')}"))
        return checks, None, None

    ev = [change.evidence_id] if change.evidence_id else []

    # --- directional ---
    if claim.direction:
        want = _DIR_ALIGN.get(claim.direction)
        got = change.direction
        if got in ("increase", "decrease"):
            verdict = AGREES if got == want else CONTRADICTS
        else:
            verdict = NO_DATA
        mag = f" ({change.pct_change:+.1f}%)" if change.pct_change is not None else ""
        checks.append(CrossCheck(
            "directional", verdict,
            f"claimed {claim.direction}; {subject.replace('_', ' ')} actually {got}{mag} "
            f"over {change.from_period}->{change.to_period}", list(ev)))

    # --- magnitude ---
    if claim.claimed_value is not None:
        checks.append(_magnitude_check(claim, change, ev))

    view = build_decomposition(engine, change, workspace=workspace)

    # --- mechanism / margin bridge ---
    if claim.mechanism_kind == "cost":
        checks.append(_cost_check(claim, view))
    elif claim.kind == "margin_move":
        checks.append(_margin_bridge_check(claim, view))
    elif claim.mechanism_kind in ("volume_pricing", "demand", "mix"):
        checks.append(CrossCheck(
            "mechanism", NO_DATA,
            f"no structured series for '{claim.mechanism}' (volume / pricing / demand are "
            f"not in the financial data); relies on the aggregates + commentary"))

    # --- segment attribution ---
    if claim.mechanism_kind == "segment" and claim.mechanism:
        checks.append(_segment_check(claim, view))

    return checks, view, change


def _magnitude_check(claim, change, ev) -> CrossCheck:
    unit = claim.claimed_unit
    if unit == "pct" and change.pct_change is not None:
        got, claimed = change.pct_change, claim.claimed_value
    elif unit == "pp" and change.abs_change is not None:
        got, claimed = change.abs_change, claim.claimed_value
    elif unit == "INR" and change.abs_change is not None:
        got, claimed = change.abs_change, claim.claimed_value
    else:
        return CrossCheck("magnitude", NO_DATA, f"cannot compare a {unit} claim to the series")
    tol = max(1.0, 0.15 * abs(claimed)) if unit != "INR" else max(abs(claimed) * 0.1, 1.0)
    same_sign = (got >= 0) == (claimed >= 0)
    verdict = AGREES if (same_sign and abs(got - claimed) <= tol) else CONTRADICTS
    return CrossCheck("magnitude", verdict,
                      f"claimed ~{claimed:g}{_u(unit)}, reported {got:+.1f}{_u(unit)}", list(ev))


def _u(unit) -> str:
    return {"pct": "%", "pp": " pp", "INR": " (abs)"}.get(unit, "")


def _cost_check(claim, view) -> CrossCheck:
    """Cost-discipline / operating-leverage claim: did costs grow slower than revenue?"""
    rev = view.components.get("revenue", {}).get("pct")
    cost = None
    for m in ("total_expenses", "employee_expense", "other_expenses"):
        c = view.components.get(m, {}).get("pct")
        if c is not None:
            cost, cost_metric = c, m
            break
    if rev is None or cost is None:
        return CrossCheck("mechanism", NO_DATA, "no comparable cost / revenue growth series")
    ev = [view.evidence[f"component_growth:{cost_metric}"]] \
        if f"component_growth:{cost_metric}" in view.evidence else []
    gap = cost - rev
    if gap <= -2.0:
        return CrossCheck("mechanism", AGREES,
                          f"{cost_metric.replace('_', ' ')} grew {gap:+.1f} pp slower than "
                          f"revenue (operating leverage visible)", ev)
    if gap >= 2.0:
        return CrossCheck("mechanism", CONTRADICTS,
                          f"{cost_metric.replace('_', ' ')} grew {gap:+.1f} pp faster than "
                          f"revenue", ev)
    return CrossCheck("mechanism", UNRELATED,
                      f"{cost_metric.replace('_', ' ')} grew about in line with revenue "
                      f"({gap:+.1f} pp)", ev)


def _margin_bridge_check(claim, view) -> CrossCheck:
    mb = view.margin_bridge or {}
    chg = mb.get("net_margin_change_pp")
    ev = [view.evidence["margin_bridge"]] if "margin_bridge" in view.evidence else []
    if chg is None:
        return CrossCheck("margin_bridge", NO_DATA, "net-margin bridge unavailable", ev)
    want_up = claim.direction != "decrease"
    verdict = AGREES if ((chg > 0) == want_up and abs(chg) >= 0.1) else (
        UNRELATED if abs(chg) < 0.1 else CONTRADICTS)
    re_, ee = mb.get("revenue_effect_pp"), mb.get("expense_effect_pp")
    split = ""
    if re_ is not None and ee is not None:
        split = f" (rev effect {re_:+.2f}, exp effect {ee:+.2f})"
    return CrossCheck("margin_bridge", verdict,
                      f"net margin moved {chg:+.2f} pp{split}", ev)


def _acronym(name: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", name)
                   if w.lower() not in ("and", "of", "the", "for"))


def _segment_check(claim, view) -> CrossCheck:
    if not view.segments:
        return CrossCheck("segment_attribution", NO_DATA,
                          "no reportable-segment data for this company")
    mech = (claim.mechanism or "").strip()
    want = set(tokenize(mech))

    def _score(seg_name: str) -> int:
        s = len(want & set(tokenize(seg_name)))
        if s == 0 and 2 <= len(mech) <= 8 and mech.replace(" ", "").isalpha() \
                and mech.replace(" ", "").lower() == _acronym(seg_name).lower():
            return 99                                   # acronym hit (BFSI -> Banking...Insurance)
        return s

    scored = sorted(((_score(s["segment"]), s) for s in view.segments),
                    key=lambda t: t[0], reverse=True)
    hits, seg = scored[0]
    if hits == 0:
        names = ", ".join(s["segment"] for s in view.segments[:4])
        return CrossCheck("segment_attribution", NO_DATA,
                          f"'{claim.mechanism}' did not match a reported segment ({names})")
    ev = [view.evidence[f"segment:{seg['segment']}"]] if f"segment:{seg['segment']}" in view.evidence else []
    share = seg.get("share_pct")
    if share is None:
        return CrossCheck("segment_attribution", NO_DATA,
                          f"{seg['segment']} has no growth-share figure", ev)
    if share >= 35:
        verdict = AGREES
    elif share <= 5:
        verdict = CONTRADICTS
    else:
        verdict = UNRELATED
    gp = seg.get("pct")
    growth = f", growth {gp:+.1f}%" if gp is not None else ""
    return CrossCheck("segment_attribution", verdict,
                      f"{seg['segment']} was {share:.0f}% of the revenue change{growth}", ev)
