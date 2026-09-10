"""Storage interfaces. Business logic depends on these Protocols, never on a driver.
Creates return the stored object with its *_id set; reads return None/[] for absence,
never raise. See docs/file-guide.md."""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional, Protocol, runtime_checkable

from .models import (
    Basis,
    Company,
    DocumentMeta,
    FinancialFact,
    Index,
    IndexMembership,
    Source,
)


@runtime_checkable
class CompanyRepository(Protocol):
    def upsert(self, company: Company) -> Company:
        """Insert or update by (ticker, exchange). Returns the row with company_id set."""

    def get(self, company_id: int) -> Optional[Company]: ...

    def get_by_ticker(self, ticker: str, exchange: str = "NSE") -> Optional[Company]: ...

    def resolve(self, token: str) -> Optional[Company]:
        """Resolve a ticker, a known alias, or an exact name to a Company."""

    def list(self, *, active: Optional[bool] = None, sector: Optional[str] = None) -> list[Company]: ...

    def add_alias(self, company_id: int, alias: str) -> None: ...


@runtime_checkable
class IndexRepository(Protocol):
    def upsert(self, index: Index) -> Index:
        """Insert or update by name. Returns the row with index_id set."""

    def get(self, index_id: int) -> Optional[Index]: ...

    def get_by_name(self, name: str) -> Optional[Index]: ...

    def list(self) -> list[Index]: ...

    def set_membership(self, membership: IndexMembership) -> None:
        """Upsert one membership row, keyed by (index_id, company_id, valid_from)."""

    def members(self, index_id: int, *, on: Optional[date] = None) -> list[Company]:
        """Companies in the index. `on=None` -> currently-active members
        (valid_to IS NULL); `on=<date>` -> members whose window covers that date."""

    def memberships_for(self, company_id: int) -> list[IndexMembership]: ...


@runtime_checkable
class SourceRepository(Protocol):
    def add(self, source: Source) -> Source: ...

    def get(self, source_id: int) -> Optional[Source]: ...

    def get_by_hash(self, content_hash: str) -> Optional[Source]:
        """De-dup helper -- returns an existing Source with the same content_hash."""


@runtime_checkable
class FinancialFactRepository(Protocol):
    def add_many(self, facts: Iterable[FinancialFact]) -> int:
        """Upsert facts, keyed by (company_id, metric, basis, period_end, period_start,
        statement_type). Returns the count written. `value is None` round-trips as NULL."""

    def get(
        self,
        *,
        company_id: int,
        metric: str,
        basis: Basis | str = Basis.CONSOLIDATED,
        financial_year: Optional[int] = None,
    ) -> list[FinancialFact]:
        """All matching facts, ordered by period_end ascending (NULLs last)."""

    def latest(
        self,
        *,
        company_id: int,
        metric: str,
        basis: Basis | str = Basis.CONSOLIDATED,
    ) -> Optional[FinancialFact]:
        """Most recent non-missing fact for the metric, or None."""

    def metrics_for(self, company_id: int) -> list[str]:
        """Distinct metric names present for the company."""


@runtime_checkable
class DocumentRepository(Protocol):
    def upsert(self, document: DocumentMeta) -> DocumentMeta: ...

    def get(self, document_id: int) -> Optional[DocumentMeta]: ...

    def for_company(
        self, company_id: int, *, document_type: Optional[str] = None
    ) -> list[DocumentMeta]: ...


class Repositories(Protocol):
    """A bundle exposing every repository over one backing store / transaction."""

    companies: CompanyRepository
    indices: IndexRepository
    sources: SourceRepository
    facts: FinancialFactRepository
    documents: DocumentRepository

    def commit(self) -> None: ...

    def close(self) -> None: ...
