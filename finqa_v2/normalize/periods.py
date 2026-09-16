"""Period normalization: raw XBRL period fields -> Indian FY, quarter, annual flag.

Indian fiscal year runs Apr 1 -> Mar 31. A date D is in FY = D.year if D.month <= 3
else D.year + 1 (so 31-Mar-2026 and 30-Jun-2025 are both FY2026).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_QUARTER_MIN_DAYS, _QUARTER_MAX_DAYS = 60, 120     # ~91-day single quarter
_ANNUAL_MIN_DAYS, _ANNUAL_MAX_DAYS = 330, 400      # ~365-day full year

_MONTH_TO_QUARTER = {                               # fiscal quarter by calendar month
    4: 1, 5: 1, 6: 1,
    7: 2, 8: 2, 9: 2,
    10: 3, 11: 3, 12: 3,
    1: 4, 2: 4, 3: 4,
}


@dataclass(frozen=True, slots=True)
class PeriodInfo:
    period_start: date | None
    period_end: date | None            # duration end, or the instant date
    financial_year: int | None
    quarter: int | None                # 1..4, only for ~single-quarter durations
    is_annual: bool
    is_point_in_time: bool             # instant-only record (no duration)


def _parse(d: str | None) -> date | None:
    if not d:
        return None
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def fiscal_year(d: date) -> int:
    return d.year if d.month <= 3 else d.year + 1


def normalize_period(
    period_start: str | date | None,
    period_end: str | date | None,
    instant: str | date | None,
) -> PeriodInfo:
    ps = period_start if isinstance(period_start, date) else _parse(period_start)
    pe = period_end if isinstance(period_end, date) else _parse(period_end)
    inst = instant if isinstance(instant, date) else _parse(instant)

    # Instant-only record: a balance-sheet snapshot with no duration.
    if inst is not None and pe is None and ps is None:
        return PeriodInfo(
            period_start=None, period_end=inst,
            financial_year=fiscal_year(inst), quarter=None,
            is_annual=False, is_point_in_time=True,
        )

    anchor = pe or inst
    fy = fiscal_year(anchor) if anchor is not None else None

    days = (pe - ps).days if (ps is not None and pe is not None) else None
    is_annual = days is not None and _ANNUAL_MIN_DAYS <= days <= _ANNUAL_MAX_DAYS
    is_quarter = days is not None and _QUARTER_MIN_DAYS <= days <= _QUARTER_MAX_DAYS
    quarter = _MONTH_TO_QUARTER[pe.month] if (is_quarter and pe is not None) else None

    return PeriodInfo(
        period_start=ps, period_end=anchor,
        financial_year=fy, quarter=quarter,
        is_annual=is_annual, is_point_in_time=False,
    )
