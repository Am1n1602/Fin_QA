"""Universe-independent domain models (frozen value objects). See docs/file-guide.md."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"


class Basis(str, Enum):
    """`consolidated_or_standalone` in section 9. Consolidated is primary; standalone
    is a diagnostic/secondary view."""

    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"


class StatementType(str, Enum):
    PROFIT_AND_LOSS = "profit_and_loss"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    SEGMENT = "segment"
    OTHER = "other"


class MappingConfidence(str, Enum):
    """How a raw source value became this canonical fact."""

    EXACT = "exact"                # direct primary canonical tag
    ALTERNATE_TAG = "alternate_tag"  # matched via a known non-primary tag
    DERIVED = "derived"            # computed from other canonical facts (e.g. bank equity = capital + reserves)
    UNMAPPED = "unmapped"          # present in the source but no canonical mapping -> value stays None


_UNSET_ID = None


@dataclass(frozen=True, slots=True)
class Company:
    """A listed company. `company_id` is the stable surrogate key; `ticker` is the
    exchange symbol and can change over time (aliases keep old ones resolvable)."""

    name: str
    ticker: str
    exchange: Exchange = Exchange.NSE
    company_id: int | None = _UNSET_ID
    isin: str | None = None
    sector: str | None = None
    industry: str | None = None
    active: bool = True
    bse_scrip: str | None = None          # retained from v1 for BSE lookups
    aliases: tuple[str, ...] = ()          # prior/alternate tickers, e.g. ("LTIM",) for LTM

    def __post_init__(self) -> None:
        if not self.name or not self.ticker:
            raise ValueError("Company requires both name and ticker")
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        object.__setattr__(self, "aliases", tuple(dict.fromkeys(self.aliases)))


@dataclass(frozen=True, slots=True)
class Index:
    """A share index or any named company set. `name` is unique. `provider` is the
    authority ('NSE', 'BSE', 'custom')."""

    name: str
    index_id: int | None = _UNSET_ID
    provider: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Index requires a name")


@dataclass(frozen=True, slots=True)
class IndexMembership:
    """`company_id` is a member of `index_id` from `valid_from` (inclusive) to
    `valid_to` (exclusive). Open-ended dates are allowed:
      valid_from is None -> membership start unknown / since inception
      valid_to   is None -> still a member
    Historical members are never deleted -- their row just gets a `valid_to`."""

    index_id: int
    company_id: int
    valid_from: date | None = None
    valid_to: date | None = None

    def is_active_on(self, on: date) -> bool:
        if self.valid_from is not None and on < self.valid_from:
            return False
        if self.valid_to is not None and on >= self.valid_to:
            return False
        return True

    @property
    def is_current(self) -> bool:
        return self.valid_to is None


@dataclass(frozen=True, slots=True)
class Source:
    """Provenance for a fact or document -- the filing/file/feed it came from."""

    kind: str                              # 'xbrl' | 'results_pdf' | 'annual_report' | 'price_feed' | 'index_csv' | ...
    source_id: int | None = _UNSET_ID
    company_id: int | None = None
    document_title: str | None = None
    uri: str | None = None                 # URL or local path
    content_hash: str | None = None        # sha256 of the raw bytes, if known
    exchange: Exchange | None = None
    retrieved_at: datetime | None = None
    period_label: str | None = None        # raw period string as-filed (pre-normalization)

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("Source requires a kind")
        if self.exchange is not None:
            object.__setattr__(self, "exchange", Exchange(self.exchange))


@dataclass(frozen=True, slots=True)
class FinancialFact:
    """One canonical financial figure for one company/period/basis (section 9).

    `value is None` is a first-class state meaning "not reported / not cleanly
    mappable" -- callers must handle it, and it must round-trip through storage
    unchanged. Never write 0.0 to mean "missing".
    """

    company_id: int
    metric: str                            # canonical name, e.g. 'revenue', 'ebitda', 'roe'
    value: float | None                    # None == missing; never 0-filled
    unit: str | None                       # 'INR' | 'pct' | 'x' | 'ratio' | 'per_share' | 'shares' | 'pp'
    statement_type: StatementType
    basis: Basis
    currency: str | None = "INR"
    period_start: date | None = None
    period_end: date | None = None
    financial_year: int | None = None      # e.g. 2026 for FY2026
    quarter: int | None = None             # 1..4, or None for annual / point-in-time
    is_annual: bool = False
    is_point_in_time: bool = False         # balance-sheet instant vs P&L duration
    source_id: int | None = None
    mapping_confidence: MappingConfidence = MappingConfidence.EXACT
    mapping_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.metric:
            raise ValueError("FinancialFact requires a metric name")
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        object.__setattr__(self, "basis", Basis(self.basis))
        object.__setattr__(self, "mapping_confidence", MappingConfidence(self.mapping_confidence))
        if self.quarter is not None and self.quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1..4 or None, got {self.quarter!r}")

    @property
    def is_missing(self) -> bool:
        return self.value is None

    def problems(self) -> list[str]:
        """Soft validation for tests / ingestion QA -- never raises."""
        out: list[str] = []
        if self.value is None and not self.mapping_reason:
            out.append("value is None but mapping_reason is empty (section 9: record why)")
        if self.value is None and self.mapping_confidence not in (
            MappingConfidence.UNMAPPED,
            MappingConfidence.DERIVED,
        ):
            out.append("value is None but mapping_confidence is not 'unmapped'/'derived'")
        if self.is_point_in_time and self.period_start is not None:
            out.append("point-in-time fact should not have a period_start")
        if not self.is_point_in_time and self.is_annual and self.quarter is not None:
            out.append("annual duration fact should not carry a quarter")
        return out


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Metadata for a source document (results PDF, annual report, transcript...).
    Page/section-level chunk storage is Phase 5 -- this is the parent record only."""

    company_id: int
    document_type: str
    title: str
    document_id: int | None = _UNSET_ID
    financial_year: int | None = None
    period_label: str | None = None
    page_count: int | None = None
    source_id: int | None = None
    is_superseded: bool = False

    def __post_init__(self) -> None:
        if not self.document_type or not self.title:
            raise ValueError("DocumentMeta requires document_type and title")
