"""Financial Engine tools (§19). Each returns a JSON-safe value dict plus the evidence
(engine result + its input facts) it produced.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from database.v2.evidence import EvidenceSet, evidence_from_engine_result, evidence_from_segment_result

_Basis = Literal["consolidated", "standalone"]


class _CoMetric(BaseModel):
    ticker: str = Field(..., description="NSE ticker, e.g. TCS")
    metric: str = Field(..., description="canonical metric or derived name (revenue, ebitda, ...)")
    basis: _Basis = "consolidated"
    period: str | int = Field("latest", description="'latest' | 'latest_annual' | 'FY2026' | 'FY2026Q1' | 2026")


class _CoRatio(BaseModel):
    ticker: str
    ratio: str = Field(..., description="roe, roce, ebitda_margin, debt_to_equity, ...")
    basis: _Basis = "consolidated"
    period: str | int = "latest"


class _Growth(BaseModel):
    ticker: str
    metric: str
    kind: Literal["yoy", "qoq"] = "yoy"
    basis: _Basis = "consolidated"


class _Cagr(BaseModel):
    ticker: str
    metric: str
    basis: _Basis = "consolidated"
    years: float | None = None


class _CompareCompanies(BaseModel):
    metric: str = Field(..., description="a metric or ratio name")
    tickers: list[str] = Field(..., min_length=1)
    basis: _Basis = "consolidated"
    period: str | int = "latest"


class _ComparePeriods(BaseModel):
    ticker: str
    metrics: list[str] = Field(..., min_length=1)
    a: str | int = Field(..., description="first period spec")
    b: str | int = Field(..., description="second period spec")
    basis: _Basis = "consolidated"


class _Segment(BaseModel):
    ticker: str
    basis: _Basis = "consolidated"
    period: str | int = "latest_annual"


class _Decompose(BaseModel):
    ticker: str
    metric: Literal["roe", "dupont", "net_margin", "net_profit_margin"] = "roe"
    basis: _Basis = "consolidated"
    period: str | int = "latest"


def _payload(res) -> tuple[dict, list[dict]]:
    ws = EvidenceSet()
    evidence_from_engine_result(res, workspace=ws)
    return (
        {
            "name": res.name, "value": res.value, "unit": res.unit, "ok": res.ok,
            "company": res.company, "basis": res.basis, "period": res.period,
            "formula": res.formula, "components": res.components,
            "limitations": list(res.limitations),
        },
        ws.to_list(),
    )


def register(reg, engine) -> None:
    reg.add("get_metric", "Core or derived financial metric for a company/period.",
            _CoMetric, lambda m: _payload(engine.get_metric(m.ticker, m.metric, basis=m.basis, period=m.period)))
    reg.add("get_ratio", "Financial ratio (ROE, ROCE, margins, leverage, ...).",
            _CoRatio, lambda m: _payload(engine.get_ratio(m.ticker, m.ratio, basis=m.basis, period=m.period)))
    reg.add("get_growth", "YoY or QoQ growth of a metric.",
            _Growth, lambda m: _payload(engine.get_growth(m.ticker, m.metric, kind=m.kind, basis=m.basis)))
    reg.add("get_cagr", "Compound annual growth rate of a metric over the available annual history.",
            _Cagr, lambda m: _payload(engine.get_cagr(m.ticker, m.metric, basis=m.basis, years=m.years)))
    reg.add("compare_companies", "Rank a set of companies on one metric/ratio for a period.",
            _CompareCompanies,
            lambda m: (engine.compare_companies(m.metric, m.tickers, basis=m.basis, period=m.period), []))
    reg.add("compare_periods", "Compare metrics for one company across two periods.",
            _ComparePeriods,
            lambda m: _payload(engine.compare_periods(m.ticker, m.metrics, basis=m.basis, a=m.a, b=m.b)))
    reg.add("get_segment_data", "Per-segment revenue and contribution % for a company/period.",
            _Segment, lambda m: _segment_payload(engine.get_segment_data(m.ticker, basis=m.basis, period=m.period)))
    reg.add("decompose_metric", "Decompose ROE (DuPont) or the net-margin change between two periods.",
            _Decompose, lambda m: _payload(engine.decompose_metric(m.ticker, m.metric, basis=m.basis, period=m.period)))


def _segment_payload(res) -> tuple[dict, list[dict]]:
    ws = EvidenceSet()
    evidence_from_segment_result(res, workspace=ws)
    rows = [
        {k: getattr(row, k) for k in row.__slots__}
        for row in res.rows
    ]
    return (
        {"kind": res.kind, "company": res.company, "basis": res.basis, "period": res.period,
         "rows": rows, "total_revenue": getattr(res, "total_revenue", None),
         "total_change": getattr(res, "total_change", None),
         "limitations": list(res.limitations), "ok": res.ok},
        ws.to_list(),
    )
