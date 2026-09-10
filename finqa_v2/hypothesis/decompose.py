"""§22 step 3: decompose the target change into structured, deterministic drivers.

Everything here comes from the Financial Engine -- component YoY growth, the net-margin
bridge, a two-endpoint DuPont diff, and segment growth. Each driver that resolves is
also written into the shared Evidence Workspace and keyed so a hypothesis built on it
can cite exactly the number it rests on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.evidence import evidence_from_engine_result, evidence_from_segment_result
from finqa_v2.hypothesis.models import MetricChange

# P&L / cash-flow lines pulled as YoY growth alongside revenue
_COMPONENTS = ("revenue", "total_expenses", "employee_expense", "other_expenses",
               "finance_costs", "depreciation", "tax_expense", "other_income",
               "operating_cash_flow", "net_profit")

_DUPONT_FACTORS = ("net_profit_margin", "asset_turnover", "equity_multiplier")


@dataclass(slots=True)
class DecompositionView:
    change: MetricChange
    components: dict = field(default_factory=dict)   # metric -> {"pct", "abs", "from", "to"}
    margin_bridge: dict | None = None               # {"expense_effect_pp", "revenue_effect_pp", ...}
    dupont: dict | None = None                      # factor -> {"from", "to", "delta"}
    segments: list = field(default_factory=list)    # [{"segment", "abs", "pct", "share_pct"}]
    evidence: dict = field(default_factory=dict)    # signal key -> evidence_id | [evidence_id, ...]

    def all_evidence_ids(self) -> list[str]:
        out: list[str] = []
        for v in self.evidence.values():
            for x in (v if isinstance(v, list) else [v]):
                if x and x not in out:
                    out.append(x)
        return out

    def summary(self) -> dict:
        out: dict[str, float] = {}
        for m, d in self.components.items():
            if d.get("pct") is not None:
                out[f"{m}_growth_pct"] = round(d["pct"], 1)
        for k in ("net_margin_change_pp", "revenue_effect_pp", "expense_effect_pp"):
            if self.margin_bridge and self.margin_bridge.get(k) is not None:
                out[k] = round(self.margin_bridge[k], 2)
        for f, d in (self.dupont or {}).items():
            if d.get("delta") is not None:
                out[f"dupont_{f}_delta"] = round(d["delta"], 3)
        for s in self.segments[:4]:
            if s.get("share_pct") is not None:
                out[f"segment[{s['segment']}]_share_of_change_pct"] = round(s["share_pct"], 0)
        return out


def build_decomposition(engine, change: MetricChange, *, workspace=None) -> DecompositionView:
    view = DecompositionView(change=change)
    tkr, basis = change.ticker, change.basis
    ws = workspace

    for m in _COMPONENTS:
        try:
            r = engine.get_growth(tkr, m, kind="yoy", basis=basis)
        except Exception:
            continue
        comp = r.components or {}
        if r.value is None and comp.get("abs_change") is None:
            continue
        view.components[m] = {"pct": r.value, "abs": comp.get("abs_change"),
                              "from": comp.get("from_value"), "to": comp.get("to_value")}
        if ws is not None and r.value is not None:
            ev, _ = evidence_from_engine_result(r, workspace=ws)
            view.evidence[f"component_growth:{m}"] = ws.add(ev)   # canonical id after dedup

    try:
        mb = engine.decompose_metric(tkr, "net_margin", basis=basis)
        if mb.components.get("available"):
            view.margin_bridge = {k: mb.components.get(k) for k in
                                  ("net_margin_change_pp", "revenue_effect_pp", "expense_effect_pp",
                                   "net_margin_prev_pct", "net_margin_curr_pct")}
            if ws is not None:
                ev, _ = evidence_from_engine_result(mb, workspace=ws)
                view.evidence["margin_bridge"] = ws.add(ev)
    except Exception:
        pass

    view.dupont = _dupont_delta(engine, change, workspace=ws, view=view)

    try:
        sg = engine.segment_growth(tkr, basis=basis, kind="yoy")
        if sg.ok:
            for row in sg.rows:
                view.segments.append({"segment": row.segment, "abs": row.abs_change,
                                      "pct": row.growth_pct,
                                      "share_pct": row.share_of_total_change_pct})
            if ws is not None:
                evs = [ws.add(e) for e in evidence_from_segment_result(sg, workspace=ws)]
                view.evidence["segment"] = evs
                for row, eid in zip(sg.rows, evs):
                    view.evidence[f"segment:{row.segment}"] = eid
    except Exception:
        pass

    return view


def _dupont_delta(engine, change: MetricChange, *, workspace=None, view=None) -> dict | None:
    if not change.from_period or not change.to_period:
        return None
    try:
        a = engine.decompose_metric(change.ticker, "roe", basis=change.basis, period=change.from_period)
        b = engine.decompose_metric(change.ticker, "roe", basis=change.basis, period=change.to_period)
    except Exception:
        return None
    ca = (a.components or {}).get("components")
    cb = (b.components or {}).get("components")
    if not ca or not cb:
        return None
    out: dict[str, dict] = {}
    for f in _DUPONT_FACTORS:
        va, vb = ca.get(f), cb.get(f)
        if va is not None and vb is not None:
            out[f] = {"from": va, "to": vb, "delta": vb - va}
    if out and workspace is not None and view is not None and b.value is not None:
        ev, _ = evidence_from_engine_result(b, workspace=workspace)
        view.evidence["dupont"] = workspace.add(ev)
    return out or None
