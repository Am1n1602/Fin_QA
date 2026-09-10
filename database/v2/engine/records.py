"""Regroup financial_facts rows into per-period records the ratio formulas expect:
one duration record (P&L / cash flow) with the balance-sheet snapshot for the same
period_end merged in.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from database.v2.models import Basis, FinancialFact


@dataclass(frozen=True, slots=True)
class PeriodRecord:
    basis: str
    period_start: date | None
    period_end: date | None
    financial_year: int | None
    quarter: int | None
    is_annual: bool
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, int | None] = field(default_factory=dict)
    review_flags: dict[str, str] = field(default_factory=dict)

    # ---- access ----
    def get(self, metric: str, default=None):
        return self.values.get(metric, default)

    def __contains__(self, metric: str) -> bool:
        return metric in self.values

    def has_all(self, *metrics: str) -> bool:
        return all(m in self.values for m in metrics)

    # ---- classification ----
    @property
    def duration_days(self) -> int | None:
        if self.period_start is None or self.period_end is None:
            return None
        return (self.period_end - self.period_start).days

    @property
    def is_single_quarter(self) -> bool:
        d = self.duration_days
        return d is not None and 71 <= d <= 111

    @property
    def is_point_in_time_only(self) -> bool:
        return self.period_start is None and self.period_end is not None

    @property
    def label(self) -> str:
        fy = f"FY{self.financial_year}" if self.financial_year else "FY?"
        if self.is_point_in_time_only:
            return f"as of {self.period_end}"
        if self.quarter:
            return f"{fy} Q{self.quarter}"
        if self.is_annual:
            return fy
        if self.period_start and self.period_end:
            return f"{self.period_start}..{self.period_end}"
        return fy

    def sort_key(self) -> tuple:
        return (
            self.period_end or date.min,
            self.period_start or date.min,
            0 if self.is_annual else 1,      # annual before quarterly on the same end date
        )


def build_period_records(repos, company_id: int, basis: Basis | str) -> list[PeriodRecord]:
    basis = Basis(basis)
    facts: list[FinancialFact] = repos.facts.list_facts(company_id, basis=basis)

    durations: dict[tuple, dict] = {}
    instants: dict[date | None, dict] = {}

    for f in facts:
        if f.is_point_in_time:
            bucket = instants.setdefault(f.period_end, {"values": {}, "sources": {}, "flags": {}})
        else:
            key = (f.period_start, f.period_end)
            bucket = durations.setdefault(
                key,
                {
                    "meta": (f.financial_year, f.quarter, f.is_annual),
                    "values": {}, "sources": {}, "flags": {},
                },
            )
        bucket["values"][f.metric] = f.value
        bucket["sources"][f.metric] = f.source_id
        if f.mapping_reason:
            bucket["flags"][f.metric] = f.mapping_reason

    records: list[PeriodRecord] = []
    used_instant_ends: set[date | None] = set()

    for (ps, pe), d in durations.items():
        fy, q, ann = d["meta"]
        values = dict(d["values"])
        sources = dict(d["sources"])
        flags = dict(d["flags"])
        snap = instants.get(pe)
        if snap is not None:
            used_instant_ends.add(pe)
            for m, v in snap["values"].items():
                values.setdefault(m, v)
                sources.setdefault(m, snap["sources"].get(m))
            for m, r in snap["flags"].items():
                flags.setdefault(m, r)
        records.append(
            PeriodRecord(
                basis=basis.value, period_start=ps, period_end=pe,
                financial_year=fy, quarter=q, is_annual=ann,
                values=values, sources=sources, review_flags=flags,
            )
        )

    # balance-sheet dates with no matching duration record -> keep as snapshot-only
    for pe, snap in instants.items():
        if pe in used_instant_ends:
            continue
        fy = pe.year if (pe and pe.month <= 3) else (pe.year + 1 if pe else None)
        records.append(
            PeriodRecord(
                basis=basis.value, period_start=None, period_end=pe,
                financial_year=fy, quarter=None, is_annual=False,
                values=dict(snap["values"]), sources=dict(snap["sources"]),
                review_flags=dict(snap["flags"]),
            )
        )

    records.sort(key=PeriodRecord.sort_key)
    return records
