"""§22 steps 1-2: detect that the target metric moved and quantify the move.

Plain metrics (revenue, net_profit, ebitda, ...) use the engine's YoY growth. Ratio
targets (margins, roe, ...) have no fact series, so the ratio is recomputed at the
latest annual period and the prior FY and differenced.
"""
from __future__ import annotations

import re

from finqa_v2.engine import ratios
from finqa_v2.evidence import evidence_from_engine_result
from finqa_v2.hypothesis.models import MetricChange

_FY_RE = re.compile(r"FY(\d{4})", re.I)


def _prior_fy(label: str | None) -> str | None:
    m = _FY_RE.fullmatch((label or "").strip())
    return f"FY{int(m.group(1)) - 1}" if m else None


def detect_metric_change(engine, ticker: str, metric: str, *, basis: str = "consolidated",
                         workspace=None) -> MetricChange | None:
    metric = (metric or "").strip() or "net_profit"
    is_ratio = ratios.get_spec(metric) is not None

    if not is_ratio:
        r = engine.get_growth(ticker, metric, kind="yoy", basis=basis)
        comp = r.components or {}
        if r.value is not None or comp.get("abs_change") is not None:
            ev_id = None
            if workspace is not None:
                ev, _ = evidence_from_engine_result(r, workspace=workspace)
                ev_id = workspace.add(ev)
            return MetricChange(
                ticker=r.company or ticker, metric=metric, basis=r.basis or basis,
                from_period=comp.get("from"), to_period=comp.get("to"),
                from_value=comp.get("from_value"), to_value=comp.get("to_value"),
                abs_change=comp.get("abs_change"), pct_change=r.value,
                unit=None, evidence_id=ev_id,
            )

    getter = (lambda p: engine.get_ratio(ticker, metric, basis=basis, period=p)) if is_ratio \
        else (lambda p: engine.get_metric(ticker, metric, basis=basis, period=p))
    latest = getter("latest_annual")
    if latest.value is None or not latest.period:
        return None
    prior_period = _prior_fy(latest.period)
    if prior_period is None:
        return None
    prev = getter(prior_period)
    if prev.value is None:
        return None

    abs_change = latest.value - prev.value
    pct_change = (abs_change / prev.value * 100) if prev.value else None
    ev_id = None
    if workspace is not None:
        e0, _ = evidence_from_engine_result(prev, workspace=workspace)
        workspace.add(e0)
        ev, _ = evidence_from_engine_result(latest, workspace=workspace)
        ev_id = workspace.add(ev)
    return MetricChange(
        ticker=latest.company or ticker, metric=metric, basis=latest.basis or basis,
        from_period=prior_period, to_period=latest.period,
        from_value=prev.value, to_value=latest.value,
        abs_change=abs_change, pct_change=pct_change,
        unit=latest.unit, evidence_id=ev_id,
    )
