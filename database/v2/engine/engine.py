"""FinancialEngine -- the deterministic §11 API over finqa_v2.db. No LLM, ever.

Every call returns an EngineResult. A missing input yields value=None with a
`limitations` entry -- never 0, never a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from database.v2.engine import decompose, derive, growth, ratios
from database.v2.engine.calculator import calculate as _calc
from database.v2.engine.records import PeriodRecord, build_period_records
from database.v2.models import Basis
from database.v2.normalize import metrics as _reg


@dataclass(frozen=True, slots=True)
class FactRef:
    metric: str
    value: float | None
    period: str | None
    source_id: int | None


@dataclass(frozen=True, slots=True)
class EngineResult:
    kind: str
    name: str
    value: float | None
    unit: str | None = None
    company: str | None = None
    basis: str | None = None
    period: str | None = None
    formula: str | None = None
    inputs: tuple[FactRef, ...] = ()
    components: dict[str, Any] = field(default_factory=dict)
    limitations: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.value is not None


class EngineError(Exception):
    pass


_DERIVED_NAMES = set(derive.DERIVED)


def _parse_period(period):
    """'latest' | 'latest_annual' | 'latest_quarter' | 2026 | 'FY2026' | 'FY2026Q1' | (2026, 1)"""
    if period in ("latest", "latest_annual", "latest_quarter"):
        return ("kind", period)
    if isinstance(period, int):
        return ("annual", period)
    if isinstance(period, tuple) and len(period) == 2:
        return ("quarter", int(period[0]), int(period[1]))
    if isinstance(period, str):
        m = re.fullmatch(r"FY(\d{4})(?:Q([1-4]))?", period.strip(), re.I)
        if m:
            return ("quarter", int(m.group(1)), int(m.group(2))) if m.group(2) else ("annual", int(m.group(1)))
    raise EngineError(f"unrecognized period spec: {period!r}")


class FinancialEngine:
    def __init__(self, repos):
        self._repos = repos
        self._cache: dict[tuple[int, str], list[PeriodRecord]] = {}

    # ------------------------------------------------------------------ #
    # infrastructure
    # ------------------------------------------------------------------ #
    def _company(self, ticker: str):
        c = self._repos.companies.resolve(ticker)
        if c is None:
            raise EngineError(f"unknown company: {ticker!r}")
        return c

    def _records(self, company_id: int, basis: Basis | str) -> list[PeriodRecord]:
        key = (company_id, Basis(basis).value)
        if key not in self._cache:
            self._cache[key] = build_period_records(self._repos, company_id, key[1])
        return self._cache[key]

    @staticmethod
    def _select(records: list[PeriodRecord], period, predicate) -> PeriodRecord | None:
        spec = _parse_period(period)
        candidates = [r for r in records if predicate(r)]
        if not candidates:
            return None
        if spec[0] == "kind":
            if spec[1] == "latest_annual":
                candidates = [r for r in candidates if r.is_annual]
            elif spec[1] == "latest_quarter":
                candidates = [r for r in candidates if r.is_single_quarter]
            return candidates[-1] if candidates else None
        if spec[0] == "annual":
            for r in reversed(candidates):
                if r.financial_year == spec[1] and r.is_annual:
                    return r
            return None
        if spec[0] == "quarter":
            for r in reversed(candidates):
                if r.financial_year == spec[1] and r.quarter == spec[2]:
                    return r
        return None

    # ------------------------------------------------------------------ #
    # §11 API
    # ------------------------------------------------------------------ #
    def get_metric(self, ticker: str, metric: str, *, basis="consolidated", period="latest") -> EngineResult:
        company = self._company(ticker)
        records = self._records(company.company_id, basis)
        metric = metric.strip()
        is_derived = metric in _DERIVED_NAMES

        def has(r: PeriodRecord) -> bool:
            if is_derived:
                return derive.DERIVED[metric](r.values) is not None
            return r.get(metric) is not None

        rec = self._select(records, period, has)
        if rec is None:
            return EngineResult(
                "metric", metric, None, company=company.ticker, basis=Basis(basis).value,
                limitations=(f"{metric!r} not reported for {company.ticker} ({basis}, period={period})",),
            )
        if is_derived:
            value = derive.DERIVED[metric](rec.values)
            unit = derive.DERIVED_UNITS.get(metric)
            used = [k for k in _derived_inputs(metric) if k in rec]
            inputs = tuple(FactRef(k, rec.get(k), rec.label, rec.sources.get(k)) for k in used)
            formula = _DERIVED_FORMULA.get(metric)
        else:
            value = rec.get(metric)
            spec = _reg.get(metric)
            unit = spec.unit if spec else None
            inputs = (FactRef(metric, value, rec.label, rec.sources.get(metric)),)
            formula = None
        return EngineResult(
            "metric", metric, value, unit=unit, company=company.ticker, basis=rec.basis,
            period=rec.label, formula=formula, inputs=inputs,
            limitations=_flag_limits(rec, [i.metric for i in inputs]),
        )

    def get_ratio(self, ticker: str, ratio: str, *, basis="consolidated", period="latest") -> EngineResult:
        company = self._company(ticker)
        spec = ratios.get_spec(ratio)
        if spec is None:
            return EngineResult("ratio", ratio, None, company=company.ticker, basis=Basis(basis).value,
                                limitations=(f"unknown ratio {ratio!r}; known: {', '.join(ratios.known())}",))
        records = self._records(company.company_id, basis)
        rec = self._select(records, period, lambda r: spec.compute(r.values) is not None)
        if rec is None:
            return EngineResult(
                "ratio", spec.name, None, unit=spec.unit, company=company.ticker, basis=Basis(basis).value,
                formula=spec.formula,
                limitations=(f"{spec.name}: inputs ({', '.join(spec.inputs)}) not all available "
                             f"for {company.ticker} ({basis}, period={period})",),
            )
        value = spec.compute(rec.values)
        used = [k for k in spec.inputs if k in rec]
        inputs = tuple(FactRef(k, rec.get(k), rec.label, rec.sources.get(k)) for k in used)
        return EngineResult(
            "ratio", spec.name, value, unit=spec.unit, company=company.ticker, basis=rec.basis,
            period=rec.label, formula=spec.formula, inputs=inputs,
            limitations=_flag_limits(rec, used),
        )

    def _series(self, records, metric, is_derived, *, only):
        out = []
        for r in records:
            if only == "annual" and not r.is_annual:
                continue
            if only == "quarter" and not r.is_single_quarter:
                continue
            v = derive.DERIVED[metric](r.values) if is_derived else r.get(metric)
            if v is not None:
                out.append((r, v))
        return out

    def get_growth(self, ticker: str, metric: str, *, kind="yoy", basis="consolidated") -> EngineResult:
        company = self._company(ticker)
        records = self._records(company.company_id, basis)
        metric = metric.strip()
        is_derived = metric in _DERIVED_NAMES
        base = EngineResult("growth", f"{metric}_{kind}", None, unit="pct",
                            company=company.ticker, basis=Basis(basis).value)

        if kind == "qoq":
            series = self._series(records, metric, is_derived, only="quarter")
            if len(series) < 2:
                return _with_limit(base, f"need >=2 quarterly periods with {metric}")
            (rp, vp), (rc, vc) = series[-2], series[-1]
        elif kind == "yoy":
            annual = self._series(records, metric, is_derived, only="annual")
            if len(annual) >= 2:
                (rp, vp), (rc, vc) = annual[-2], annual[-1]
            else:
                q = self._series(records, metric, is_derived, only="quarter")
                if not q:
                    return _with_limit(base, f"no periods with {metric}")
                rc, vc = q[-1]
                match = [(r, v) for r, v in q
                         if r.quarter == rc.quarter and r.financial_year == (rc.financial_year or 0) - 1]
                if not match:
                    return _with_limit(base, f"need two comparable annual periods, or {metric} "
                                             f"for {rc.quarter} of the prior FY")
                rp, vp = match[-1]
        else:
            return _with_limit(base, f"unknown growth kind {kind!r} (use 'yoy' or 'qoq')")

        return EngineResult(
            "growth", f"{metric}_{kind}", growth.pct_change(vp, vc), unit="pct",
            company=company.ticker, basis=Basis(basis).value,
            period=f"{rp.label} -> {rc.label}",
            formula="(curr - prev) / prev * 100",
            inputs=(FactRef(metric, vp, rp.label, None), FactRef(metric, vc, rc.label, None)),
            components={"abs_change": growth.abs_change(vp, vc), "from": rp.label, "to": rc.label,
                        "from_value": vp, "to_value": vc},
            limitations=() if vp > 0 else ("prior value <= 0; % change not meaningful, see components.abs_change",),
        )

    def get_cagr(self, ticker: str, metric: str, *, basis="consolidated", years: float | None = None) -> EngineResult:
        company = self._company(ticker)
        records = self._records(company.company_id, basis)
        metric = metric.strip()
        is_derived = metric in _DERIVED_NAMES
        annual = self._series(records, metric, is_derived, only="annual")
        base = EngineResult("cagr", f"{metric}_cagr", None, unit="pct",
                            company=company.ticker, basis=Basis(basis).value)
        if len(annual) < 2:
            return _with_limit(base, f"need >=2 annual periods with {metric}")
        (rp, vp), (rc, vc) = annual[0], annual[-1]
        span = years if years is not None else (
            (rc.financial_year - rp.financial_year) if (rc.financial_year and rp.financial_year) else len(annual) - 1
        )
        return EngineResult(
            "cagr", f"{metric}_cagr", growth.cagr(vp, vc, span), unit="pct",
            company=company.ticker, basis=Basis(basis).value,
            period=f"{rp.label} -> {rc.label}", formula="(end/start)**(1/years) - 1, x100",
            inputs=(FactRef(metric, vp, rp.label, None), FactRef(metric, vc, rc.label, None)),
            components={"years": span, "start_value": vp, "end_value": vc},
            limitations=() if vp > 0 else ("start value <= 0; CAGR undefined",),
        )

    def compare_periods(self, ticker: str, metrics, *, basis="consolidated", a, b) -> EngineResult:
        company = self._company(ticker)
        records = self._records(company.company_id, basis)
        ra = self._select(records, a, lambda r: True)
        rb = self._select(records, b, lambda r: True)
        if ra is None or rb is None:
            return EngineResult("comparison", "compare_periods", None, company=company.ticker,
                                basis=Basis(basis).value,
                                limitations=(f"could not resolve period(s): a={a!r} b={b!r}",))
        comp = {}
        for m in ([metrics] if isinstance(metrics, str) else list(metrics)):
            va = derive.DERIVED[m](ra.values) if m in _DERIVED_NAMES else ra.get(m)
            vb = derive.DERIVED[m](rb.values) if m in _DERIVED_NAMES else rb.get(m)
            comp[m] = {"from": va, "to": vb, "abs_change": growth.abs_change(va, vb),
                       "pct_change": growth.pct_change(va, vb)}
        return EngineResult("comparison", "compare_periods", None, company=company.ticker,
                            basis=Basis(basis).value, period=f"{ra.label} -> {rb.label}",
                            components=comp)

    def compare_companies(self, metric: str, tickers, *, basis="consolidated", period="latest") -> dict:
        is_ratio = ratios.get_spec(metric) is not None
        results, missing = [], []
        unit = None
        for t in tickers:
            try:
                r = self.get_ratio(t, metric, basis=basis, period=period) if is_ratio \
                    else self.get_metric(t, metric, basis=basis, period=period)
            except EngineError as e:
                missing.append({"ticker": t, "reason": str(e)})
                continue
            unit = r.unit or unit
            if r.value is None:
                missing.append({"ticker": t, "reason": r.limitations[0] if r.limitations else "no data"})
            else:
                results.append({"ticker": t, "value": r.value, "period": r.period})
        results.sort(key=lambda x: x["value"], reverse=True)
        for i, row in enumerate(results, 1):
            row["rank"] = i
        return {"metric": metric, "kind": "ratio" if is_ratio else "metric", "unit": unit,
                "basis": Basis(basis).value, "period": period, "results": results, "missing": missing}

    def decompose_metric(self, ticker: str, metric: str, *, basis="consolidated", period="latest") -> EngineResult:
        company = self._company(ticker)
        records = self._records(company.company_id, basis)
        key = metric.strip().lower()
        if key in ("roe", "dupont"):
            rec = self._select(records, period, lambda r: r.has_all("net_profit", "revenue", "total_assets", "total_equity"))
            if rec is None:
                return EngineResult("decomposition", "dupont_roe", None, company=company.ticker,
                                    basis=Basis(basis).value,
                                    limitations=("DuPont needs net_profit, revenue, total_assets, total_equity "
                                                 f"in one period ({company.ticker}, {basis}, {period})",))
            d = decompose.dupont_roe(rec)
            return EngineResult("decomposition", "dupont_roe", d["actual_roe_pct"], unit="pct",
                                company=company.ticker, basis=rec.basis, period=rec.label,
                                formula="npm x asset_turnover x equity_multiplier",
                                components=d, limitations=_flag_limits(rec, ["net_profit", "revenue", "total_assets", "total_equity"]))
        if key in ("net_margin", "net_profit_margin", "margin"):
            annual = [r for r in records if r.is_annual and r.has_all("revenue", "total_expenses", "net_profit")]
            qtr = [r for r in records if r.is_single_quarter and r.has_all("revenue", "total_expenses", "net_profit")]
            seq = annual if len(annual) >= 2 else qtr
            if len(seq) < 2:
                return EngineResult("decomposition", "net_margin_bridge", None, company=company.ticker,
                                    basis=Basis(basis).value,
                                    limitations=("need two comparable periods with revenue/total_expenses/net_profit",))
            d = decompose.net_margin_bridge(seq[-2], seq[-1])
            return EngineResult("decomposition", "net_margin_bridge",
                                d.get("net_margin_change_pp"), unit="pp",
                                company=company.ticker, basis=Basis(basis).value,
                                period=f"{seq[-2].label} -> {seq[-1].label}", components=d)
        return EngineResult("decomposition", key, None, company=company.ticker, basis=Basis(basis).value,
                            limitations=(f"no decomposition for {metric!r}; try 'roe' or 'net_margin'",))

    def calculate(self, expr: str, **vars: Any) -> EngineResult:
        try:
            v = _calc(expr, **vars)
        except ValueError as e:
            return EngineResult("calculation", "calculate", None, formula=expr, limitations=(str(e),))
        return EngineResult("calculation", "calculate", v, formula=expr, components=dict(vars))

    def get_segment_data(self, *args, **kwargs):
        raise NotImplementedError("segment intelligence is roadmap Phase 4")

    # ------------------------------------------------------------------ #
    # introspection helpers
    # ------------------------------------------------------------------ #
    def periods(self, ticker: str, *, basis="consolidated") -> list[str]:
        return [r.label for r in self._records(self._company(ticker).company_id, basis)]

    def available_metrics(self, ticker: str, *, basis="consolidated") -> list[str]:
        seen: set[str] = set()
        for r in self._records(self._company(ticker).company_id, basis):
            seen.update(r.values)
        return sorted(seen)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

_DERIVED_INPUTS = {
    "ebit": ("pbt_before_exceptional", "finance_costs"),
    "operating_ebit": ("revenue", "employee_expense", "depreciation", "other_expenses"),
    "ebitda": ("pbt_before_exceptional", "depreciation", "finance_costs", "other_income"),
    "total_debt": ("borrowings_current", "borrowings_noncurrent", "debt_securities", "deposits_debt"),
    "net_debt": ("borrowings_current", "borrowings_noncurrent", "debt_securities", "deposits_debt", "cash_and_equivalents"),
    "capex": ("capex_ppe", "capex_intangibles"),
    "shares_outstanding": ("paid_up_equity_capital", "face_value_per_share"),
}
_DERIVED_FORMULA = {
    "ebit": "pbt_before_exceptional + finance_costs",
    "operating_ebit": "revenue - employee_expense - depreciation - other_expenses",
    "ebitda": "pbt_before_exceptional + depreciation + finance_costs - other_income",
    "total_debt": "borrowings_current + borrowings_noncurrent + debt_securities + deposits_debt",
    "net_debt": "total_debt - cash_and_equivalents",
    "capex": "capex_ppe + capex_intangibles",
    "shares_outstanding": "paid_up_equity_capital / face_value_per_share",
}


def _derived_inputs(name: str) -> tuple[str, ...]:
    return _DERIVED_INPUTS.get(name, ())


def _flag_limits(rec: PeriodRecord, used: list[str]) -> tuple[str, ...]:
    return tuple(
        f"{m}: source record flagged for review ({rec.review_flags[m]})"
        for m in used if m in rec.review_flags
    )


def _with_limit(res: EngineResult, msg: str) -> EngineResult:
    return EngineResult(
        res.kind, res.name, None, unit=res.unit, company=res.company, basis=res.basis,
        limitations=res.limitations + (msg,),
    )
