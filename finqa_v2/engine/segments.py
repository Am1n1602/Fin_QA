"""Segment revenue intelligence (§12): per-segment revenue, contribution %, YoY growth,
and each segment's share of the total revenue change. No LLM.

Segment margin is not computed: the structured filings carry SegmentRevenue only, no
SegmentResult -- reported as a limitation rather than approximated (§9).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from finqa_v2.engine.growth import abs_change, pct_change
from finqa_v2.models import Basis, SegmentFact


@dataclass(frozen=True, slots=True)
class SegmentRow:
    segment: str
    revenue: float | None
    contribution_pct: float | None
    period: str | None = None


@dataclass(frozen=True, slots=True)
class SegmentGrowthRow:
    segment: str
    from_revenue: float | None
    to_revenue: float | None
    abs_change: float | None
    growth_pct: float | None
    share_of_total_change_pct: float | None


@dataclass(frozen=True, slots=True)
class SegmentResult:
    kind: str
    company: str
    basis: str
    period: str | None
    rows: tuple
    total_revenue: float | None = None
    total_change: float | None = None
    limitations: tuple[str, ...] = ()
    components: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.rows)


def _label(f: SegmentFact) -> str:
    fy = f"FY{f.financial_year}" if f.financial_year else "FY?"
    if f.quarter:
        return f"{fy} Q{f.quarter}"
    return fy if f.is_annual else (f"{f.period_start}..{f.period_end}" if f.period_start else fy)


def _period_matches(f: SegmentFact, spec) -> bool:
    if spec in ("latest", "latest_annual"):
        return f.is_annual
    if spec == "latest_quarter":
        return f.quarter is not None
    if isinstance(spec, int):
        return f.is_annual and f.financial_year == spec
    if isinstance(spec, tuple) and len(spec) == 2:
        return f.financial_year == spec[0] and f.quarter == spec[1]
    if isinstance(spec, str):
        import re
        m = re.fullmatch(r"FY(\d{4})(?:Q([1-4]))?", spec, re.I)
        if m and m.group(2):
            return f.financial_year == int(m.group(1)) and f.quarter == int(m.group(2))
        if m:
            return f.is_annual and f.financial_year == int(m.group(1))
    return False


class SegmentEngine:
    def __init__(self, repos):
        self._repos = repos

    def _revenue_facts(self, company_id: int, basis) -> list[SegmentFact]:
        return [
            f for f in self._repos.segments.list_segment_facts(
                company_id, metric="segment_revenue", basis=Basis(basis)
            )
        ]

    def _pick_period_facts(self, facts: list[SegmentFact], period) -> list[SegmentFact]:
        cand = [f for f in facts if _period_matches(f, period)]
        if not cand:
            return []
        latest_end = max(f.period_end for f in cand if f.period_end is not None)
        # among the matching period, keep the most recent end date's set
        chosen = [f for f in cand if f.period_end == latest_end]
        if isinstance(period, (int, tuple, str)):
            return chosen
        return chosen  # 'latest*' already reduced to the newest end

    def get_segment_data(self, ticker: str, *, basis="consolidated", period="latest_annual") -> SegmentResult:
        company = self._repos.companies.resolve(ticker)
        if company is None:
            return SegmentResult("segment_data", ticker, Basis(basis).value, None, (),
                                 limitations=(f"unknown company {ticker!r}",))
        facts = self._pick_period_facts(self._revenue_facts(company.company_id, basis), period)
        if not facts:
            return SegmentResult(
                "segment_data", company.ticker, Basis(basis).value, None, (),
                limitations=(f"no reportable-segment revenue for {company.ticker} "
                             f"({basis}, period={period}) -- single-segment or not disclosed in XBRL",),
            )
        seg_name = {s.segment_id: s.name for s in self._repos.segments.segments_for(company.company_id)}
        total = sum(f.value for f in facts if f.value is not None) or None
        rows = tuple(
            SegmentRow(
                segment=seg_name.get(f.segment_id, str(f.segment_id)),
                revenue=f.value,
                contribution_pct=(f.value / total * 100) if (total and f.value is not None) else None,
                period=_label(f),
            )
            for f in sorted(facts, key=lambda x: (x.value is None, -(x.value or 0)))
        )
        return SegmentResult("segment_data", company.ticker, Basis(basis).value,
                             _label(facts[0]), rows, total_revenue=total,
                             limitations=("segment margin not available: filings report segment revenue only",))

    def segment_growth(self, ticker: str, *, basis="consolidated", kind="yoy") -> SegmentResult:
        company = self._repos.companies.resolve(ticker)
        if company is None:
            return SegmentResult("segment_growth", ticker, Basis(basis).value, None, (),
                                 limitations=(f"unknown company {ticker!r}",))
        facts = self._revenue_facts(company.company_id, basis)
        only_annual = [f for f in facts if f.is_annual]
        only_qtr = [f for f in facts if f.quarter is not None]
        series = only_annual if kind == "yoy" and len(only_annual) else only_qtr

        ends = sorted({f.period_end for f in series if f.period_end})
        if len(ends) < 2:
            return SegmentResult("segment_growth", company.ticker, Basis(basis).value, None, (),
                                 limitations=(f"need two comparable periods of segment revenue for {company.ticker}",))
        prev_end, curr_end = ends[-2], ends[-1]
        seg_name = {s.segment_id: s.name for s in self._repos.segments.segments_for(company.company_id)}
        prev = {f.segment_id: f.value for f in series if f.period_end == prev_end}
        curr = {f.segment_id: f.value for f in series if f.period_end == curr_end}

        total_prev = sum(v for v in prev.values() if v is not None) or None
        total_curr = sum(v for v in curr.values() if v is not None) or None
        total_delta = abs_change(total_prev, total_curr)

        rows = []
        for sid in sorted(set(prev) | set(curr)):
            vp, vc = prev.get(sid), curr.get(sid)
            delta = abs_change(vp, vc)
            rows.append(SegmentGrowthRow(
                segment=seg_name.get(sid, str(sid)),
                from_revenue=vp, to_revenue=vc,
                abs_change=delta,
                growth_pct=pct_change(vp, vc),
                share_of_total_change_pct=(delta / total_delta * 100) if (total_delta and delta is not None) else None,
            ))
        rows.sort(key=lambda r: (r.abs_change is None, -(r.abs_change or 0)))
        return SegmentResult(
            "segment_growth", company.ticker, Basis(basis).value,
            f"{prev_end} -> {curr_end}", tuple(rows),
            total_change=total_delta,
            components={"total_from": total_prev, "total_to": total_curr},
        )
