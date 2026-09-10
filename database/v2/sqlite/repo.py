"""SQLite implementation of the database.v2 repositories. See docs/file-guide.md."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Optional

from database.v2.models import (
    Basis,
    Company,
    DocumentMeta,
    Exchange,
    FinancialFact,
    Index,
    IndexMembership,
    MappingConfidence,
    Source,
    StatementType,
)

_PKG_ROOT = Path(__file__).resolve().parents[2]          # .../database
DEFAULT_V2_DB_PATH = _PKG_ROOT / "data" / "finqa_v2.db"
_SCHEMA_PATH = Path(__file__).with_name("schema_v2.sql")


# --------------------------------------------------------------------------- #
# connection / bootstrap
# --------------------------------------------------------------------------- #

def connect(db_path: str | Path = DEFAULT_V2_DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    if db_path != Path(":memory:") and str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


# --------------------------------------------------------------------------- #
# scalar helpers
# --------------------------------------------------------------------------- #

def _d(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


def _ds(d: Optional[date]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _dt(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s) if s else None


def _dts(d: Optional[datetime]) -> Optional[str]:
    return d.isoformat() if d is not None else None


def _b(v) -> bool:
    return bool(v)


# --------------------------------------------------------------------------- #
# row -> model
# --------------------------------------------------------------------------- #

def _row_company(r: sqlite3.Row, aliases: tuple[str, ...] = ()) -> Company:
    return Company(
        company_id=r["company_id"],
        name=r["name"],
        ticker=r["ticker"],
        exchange=Exchange(r["exchange"]),
        isin=r["isin"],
        sector=r["sector"],
        industry=r["industry"],
        active=_b(r["active"]),
        bse_scrip=r["bse_scrip"],
        aliases=aliases,
    )


def _row_index(r: sqlite3.Row) -> Index:
    return Index(index_id=r["index_id"], name=r["name"], provider=r["provider"])


def _row_membership(r: sqlite3.Row) -> IndexMembership:
    return IndexMembership(
        index_id=r["index_id"],
        company_id=r["company_id"],
        valid_from=_d(r["valid_from"]),
        valid_to=_d(r["valid_to"]),
    )


def _row_source(r: sqlite3.Row) -> Source:
    return Source(
        source_id=r["source_id"],
        kind=r["kind"],
        company_id=r["company_id"],
        document_title=r["document_title"],
        uri=r["uri"],
        content_hash=r["content_hash"],
        exchange=Exchange(r["exchange"]) if r["exchange"] else None,
        retrieved_at=_dt(r["retrieved_at"]),
        period_label=r["period_label"],
    )


def _row_fact(r: sqlite3.Row) -> FinancialFact:
    return FinancialFact(
        company_id=r["company_id"],
        metric=r["metric"],
        value=r["value"],                       # stays None when NULL
        unit=r["unit"],
        currency=r["currency"],
        period_start=_d(r["period_start"]),
        period_end=_d(r["period_end"]),
        financial_year=r["financial_year"],
        quarter=r["quarter"],
        statement_type=StatementType(r["statement_type"]),
        basis=Basis(r["basis"]),
        is_annual=_b(r["is_annual"]),
        is_point_in_time=_b(r["is_point_in_time"]),
        source_id=r["source_id"],
        mapping_confidence=MappingConfidence(r["mapping_confidence"]),
        mapping_reason=r["mapping_reason"],
    )


def _row_document(r: sqlite3.Row) -> DocumentMeta:
    return DocumentMeta(
        document_id=r["document_id"],
        company_id=r["company_id"],
        document_type=r["document_type"],
        title=r["title"],
        financial_year=r["financial_year"],
        period_label=r["period_label"],
        page_count=r["page_count"],
        source_id=r["source_id"],
        is_superseded=_b(r["is_superseded"]),
    )


# --------------------------------------------------------------------------- #
# repositories
# --------------------------------------------------------------------------- #

class SqliteCompanyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def _aliases(self, company_id: int) -> tuple[str, ...]:
        rows = self._c.execute(
            "SELECT alias FROM company_aliases WHERE company_id = ? ORDER BY alias",
            (company_id,),
        ).fetchall()
        return tuple(r["alias"] for r in rows)

    def upsert(self, company: Company) -> Company:
        self._c.execute(
            """
            INSERT INTO companies (name, ticker, exchange, isin, sector, industry, active, bse_scrip)
            VALUES (:name, :ticker, :exchange, :isin, :sector, :industry, :active, :bse_scrip)
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                name      = excluded.name,
                isin      = COALESCE(excluded.isin, companies.isin),
                sector    = COALESCE(excluded.sector, companies.sector),
                industry  = COALESCE(excluded.industry, companies.industry),
                active    = excluded.active,
                bse_scrip = COALESCE(excluded.bse_scrip, companies.bse_scrip)
            """,
            {
                "name": company.name,
                "ticker": company.ticker,
                "exchange": company.exchange.value,
                "isin": company.isin,
                "sector": company.sector,
                "industry": company.industry,
                "active": int(company.active),
                "bse_scrip": company.bse_scrip,
            },
        )
        row = self._c.execute(
            "SELECT * FROM companies WHERE ticker = ? AND exchange = ?",
            (company.ticker, company.exchange.value),
        ).fetchone()
        for alias in company.aliases:
            self.add_alias(row["company_id"], alias)
        return _row_company(row, self._aliases(row["company_id"]))

    def get(self, company_id: int) -> Optional[Company]:
        row = self._c.execute(
            "SELECT * FROM companies WHERE company_id = ?", (company_id,)
        ).fetchone()
        return _row_company(row, self._aliases(company_id)) if row else None

    def get_by_ticker(self, ticker: str, exchange: str = "NSE") -> Optional[Company]:
        row = self._c.execute(
            "SELECT * FROM companies WHERE ticker = ? AND exchange = ?",
            (ticker, Exchange(exchange).value),
        ).fetchone()
        return _row_company(row, self._aliases(row["company_id"])) if row else None

    def resolve(self, token: str) -> Optional[Company]:
        token = (token or "").strip()
        if not token:
            return None
        row = self._c.execute(
            "SELECT * FROM companies WHERE ticker = ? COLLATE NOCASE", (token,)
        ).fetchone()
        if row is None:
            row = self._c.execute(
                """SELECT c.* FROM companies c
                   JOIN company_aliases a ON a.company_id = c.company_id
                   WHERE a.alias = ? COLLATE NOCASE""",
                (token,),
            ).fetchone()
        if row is None:
            row = self._c.execute(
                "SELECT * FROM companies WHERE name = ? COLLATE NOCASE", (token,)
            ).fetchone()
        return _row_company(row, self._aliases(row["company_id"])) if row else None

    def list(self, *, active: Optional[bool] = None, sector: Optional[str] = None) -> list[Company]:
        clauses, params = [], []
        if active is not None:
            clauses.append("active = ?")
            params.append(int(active))
        if sector is not None:
            clauses.append("sector = ?")
            params.append(sector)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._c.execute(
            f"SELECT * FROM companies{where} ORDER BY ticker", params
        ).fetchall()
        return [_row_company(r, self._aliases(r["company_id"])) for r in rows]

    def add_alias(self, company_id: int, alias: str) -> None:
        if not alias:
            return
        self._c.execute(
            "INSERT OR IGNORE INTO company_aliases (company_id, alias) VALUES (?, ?)",
            (company_id, alias),
        )


class SqliteIndexRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def upsert(self, index: Index) -> Index:
        self._c.execute(
            """INSERT INTO indices (name, provider) VALUES (?, ?)
               ON CONFLICT (name) DO UPDATE SET provider = COALESCE(excluded.provider, indices.provider)""",
            (index.name, index.provider),
        )
        row = self._c.execute("SELECT * FROM indices WHERE name = ?", (index.name,)).fetchone()
        return _row_index(row)

    def get(self, index_id: int) -> Optional[Index]:
        row = self._c.execute("SELECT * FROM indices WHERE index_id = ?", (index_id,)).fetchone()
        return _row_index(row) if row else None

    def get_by_name(self, name: str) -> Optional[Index]:
        row = self._c.execute("SELECT * FROM indices WHERE name = ?", (name,)).fetchone()
        return _row_index(row) if row else None

    def list(self) -> list[Index]:
        rows = self._c.execute("SELECT * FROM indices ORDER BY name").fetchall()
        return [_row_index(r) for r in rows]

    def set_membership(self, membership: IndexMembership) -> None:
        self._c.execute(
            """
            INSERT INTO index_memberships (index_id, company_id, valid_from, valid_to)
            VALUES (:index_id, :company_id, :valid_from, :valid_to)
            ON CONFLICT (index_id, company_id, COALESCE(valid_from, '')) DO UPDATE SET
                valid_to = excluded.valid_to
            """,
            {
                "index_id": membership.index_id,
                "company_id": membership.company_id,
                "valid_from": _ds(membership.valid_from),
                "valid_to": _ds(membership.valid_to),
            },
        )

    def members(self, index_id: int, *, on: Optional[date] = None) -> list[Company]:
        if on is None:
            rows = self._c.execute(
                """SELECT c.* FROM companies c
                   JOIN index_memberships m ON m.company_id = c.company_id
                   WHERE m.index_id = ? AND m.valid_to IS NULL
                   ORDER BY c.ticker""",
                (index_id,),
            ).fetchall()
        else:
            iso = on.isoformat()
            rows = self._c.execute(
                """SELECT c.* FROM companies c
                   JOIN index_memberships m ON m.company_id = c.company_id
                   WHERE m.index_id = ?
                     AND (m.valid_from IS NULL OR m.valid_from <= ?)
                     AND (m.valid_to   IS NULL OR m.valid_to   >  ?)
                   ORDER BY c.ticker""",
                (index_id, iso, iso),
            ).fetchall()
        cr = SqliteCompanyRepository(self._c)
        return [_row_company(r, cr._aliases(r["company_id"])) for r in rows]

    def memberships_for(self, company_id: int) -> list[IndexMembership]:
        rows = self._c.execute(
            "SELECT * FROM index_memberships WHERE company_id = ? ORDER BY index_id, valid_from",
            (company_id,),
        ).fetchall()
        return [_row_membership(r) for r in rows]


class SqliteSourceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def add(self, source: Source) -> Source:
        if source.content_hash:
            existing = self.get_by_hash(source.content_hash)
            if existing is not None:
                return existing
        cur = self._c.execute(
            """INSERT INTO sources
               (kind, company_id, document_title, uri, content_hash, exchange, retrieved_at, period_label)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source.kind,
                source.company_id,
                source.document_title,
                source.uri,
                source.content_hash,
                source.exchange.value if source.exchange else None,
                _dts(source.retrieved_at),
                source.period_label,
            ),
        )
        row = self._c.execute(
            "SELECT * FROM sources WHERE source_id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_source(row)

    def get(self, source_id: int) -> Optional[Source]:
        row = self._c.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return _row_source(row) if row else None

    def get_by_hash(self, content_hash: str) -> Optional[Source]:
        row = self._c.execute(
            "SELECT * FROM sources WHERE content_hash = ?", (content_hash,)
        ).fetchone()
        return _row_source(row) if row else None


class SqliteFinancialFactRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def add_many(self, facts: Iterable[FinancialFact]) -> int:
        n = 0
        for f in facts:
            self._c.execute(
                """
                INSERT INTO financial_facts
                    (company_id, metric, value, unit, currency, period_start, period_end,
                     financial_year, quarter, statement_type, basis, is_annual, is_point_in_time,
                     source_id, mapping_confidence, mapping_reason)
                VALUES
                    (:company_id, :metric, :value, :unit, :currency, :period_start, :period_end,
                     :financial_year, :quarter, :statement_type, :basis, :is_annual, :is_point_in_time,
                     :source_id, :mapping_confidence, :mapping_reason)
                ON CONFLICT (company_id, metric, basis, statement_type,
                             COALESCE(period_end, ''), COALESCE(period_start, ''))
                DO UPDATE SET
                    value              = excluded.value,
                    unit               = excluded.unit,
                    currency           = excluded.currency,
                    financial_year     = excluded.financial_year,
                    quarter            = excluded.quarter,
                    is_annual          = excluded.is_annual,
                    is_point_in_time   = excluded.is_point_in_time,
                    source_id          = COALESCE(excluded.source_id, financial_facts.source_id),
                    mapping_confidence = excluded.mapping_confidence,
                    mapping_reason     = excluded.mapping_reason
                """,
                {
                    "company_id": f.company_id,
                    "metric": f.metric,
                    "value": f.value,                       # None -> NULL, never 0
                    "unit": f.unit,
                    "currency": f.currency,
                    "period_start": _ds(f.period_start),
                    "period_end": _ds(f.period_end),
                    "financial_year": f.financial_year,
                    "quarter": f.quarter,
                    "statement_type": f.statement_type.value,
                    "basis": f.basis.value,
                    "is_annual": int(f.is_annual),
                    "is_point_in_time": int(f.is_point_in_time),
                    "source_id": f.source_id,
                    "mapping_confidence": f.mapping_confidence.value,
                    "mapping_reason": f.mapping_reason,
                },
            )
            n += 1
        return n

    def get(
        self,
        *,
        company_id: int,
        metric: str,
        basis: Basis | str = Basis.CONSOLIDATED,
        financial_year: Optional[int] = None,
    ) -> list[FinancialFact]:
        clauses = ["company_id = ?", "metric = ?", "basis = ?"]
        params: list = [company_id, metric, Basis(basis).value]
        if financial_year is not None:
            clauses.append("financial_year = ?")
            params.append(financial_year)
        rows = self._c.execute(
            f"""SELECT * FROM financial_facts
                WHERE {' AND '.join(clauses)}
                ORDER BY (period_end IS NULL), period_end""",
            params,
        ).fetchall()
        return [_row_fact(r) for r in rows]

    def latest(
        self,
        *,
        company_id: int,
        metric: str,
        basis: Basis | str = Basis.CONSOLIDATED,
    ) -> Optional[FinancialFact]:
        row = self._c.execute(
            """SELECT * FROM financial_facts
               WHERE company_id = ? AND metric = ? AND basis = ? AND value IS NOT NULL
               ORDER BY (period_end IS NULL), period_end DESC
               LIMIT 1""",
            (company_id, metric, Basis(basis).value),
        ).fetchone()
        return _row_fact(row) if row else None

    def metrics_for(self, company_id: int) -> list[str]:
        rows = self._c.execute(
            "SELECT DISTINCT metric FROM financial_facts WHERE company_id = ? ORDER BY metric",
            (company_id,),
        ).fetchall()
        return [r["metric"] for r in rows]


class SqliteDocumentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._c = conn

    def upsert(self, document: DocumentMeta) -> DocumentMeta:
        if document.document_id is not None:
            self._c.execute(
                """UPDATE documents SET
                       company_id=?, document_type=?, title=?, financial_year=?,
                       period_label=?, page_count=?, source_id=?, is_superseded=?
                   WHERE document_id=?""",
                (
                    document.company_id, document.document_type, document.title,
                    document.financial_year, document.period_label, document.page_count,
                    document.source_id, int(document.is_superseded), document.document_id,
                ),
            )
            row = self._c.execute(
                "SELECT * FROM documents WHERE document_id = ?", (document.document_id,)
            ).fetchone()
            return _row_document(row)
        cur = self._c.execute(
            """INSERT INTO documents
               (company_id, document_type, title, financial_year, period_label, page_count,
                source_id, is_superseded)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                document.company_id, document.document_type, document.title,
                document.financial_year, document.period_label, document.page_count,
                document.source_id, int(document.is_superseded),
            ),
        )
        row = self._c.execute(
            "SELECT * FROM documents WHERE document_id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_document(row)

    def get(self, document_id: int) -> Optional[DocumentMeta]:
        row = self._c.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
        return _row_document(row) if row else None

    def for_company(
        self, company_id: int, *, document_type: Optional[str] = None
    ) -> list[DocumentMeta]:
        if document_type is None:
            rows = self._c.execute(
                "SELECT * FROM documents WHERE company_id = ? ORDER BY financial_year DESC, document_id",
                (company_id,),
            ).fetchall()
        else:
            rows = self._c.execute(
                """SELECT * FROM documents WHERE company_id = ? AND document_type = ?
                   ORDER BY financial_year DESC, document_id""",
                (company_id, document_type),
            ).fetchall()
        return [_row_document(r) for r in rows]


# --------------------------------------------------------------------------- #
# bundle
# --------------------------------------------------------------------------- #

class SqliteRepositories:
    """Opens finqa_v2.db (applying the schema), exposes every repository over one
    connection, and acts as a context manager."""

    def __init__(self, db_path: str | Path = DEFAULT_V2_DB_PATH) -> None:
        self._conn = connect(db_path)
        init_db(self._conn)
        self.companies = SqliteCompanyRepository(self._conn)
        self.indices = SqliteIndexRepository(self._conn)
        self.sources = SqliteSourceRepository(self._conn)
        self.facts = SqliteFinancialFactRepository(self._conn)
        self.documents = SqliteDocumentRepository(self._conn)

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteRepositories":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        self._conn.close()
