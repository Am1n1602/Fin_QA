"""PostgreSQL implementation of the finqa_v2 repositories (§7 / §17).

The whole point of §17 is that nothing above the repository layer changes. We get
that here by REUSING every `Sqlite*Repository` class body unchanged and feeding it a
thin psycopg3 connection adapter (`_PgConn`) that:

  * rewrites the SQL dialect on the fly -- `:name` -> `%(name)s`, bare `?` -> `%s`,
    `x = ? COLLATE NOCASE` -> `x ILIKE %s`, `INSERT OR IGNORE` -> `... ON CONFLICT
    DO NOTHING`, and appends `RETURNING <pk>` where the SQLite code relied on
    `cursor.lastrowid`;
  * returns rows that support both `row["col"]` and `row[0]` so the shared
    `_row_*` mappers and the few positional `.fetchone()[0]` call sites both work.

Date/datetime columns are TEXT (ISO strings) and booleans are INTEGER 0/1 in the
Postgres schema too, so `_ds/_d/_b` and the mappers are identical across backends.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from finqa_v2.sqlite.repo import (
    SqliteCompanyRepository,
    SqliteDocumentRepository,
    SqliteFinancialFactRepository,
    SqliteIndexRepository,
    SqliteSegmentRepository,
    SqliteSharePriceRepository,
    SqliteSourceRepository,
)

_SCHEMA = Path(__file__).with_name("schema_pg.sql")

# INSERT statements whose SQLite version leaned on cursor.lastrowid
_PK_BY_TABLE = {
    "sources": "source_id",
    "documents": "document_id",
    "financial_facts": "fact_id",
    "segment_facts": "segment_fact_id",
    "share_prices": "price_id",
    "companies": "company_id",
    "segments": "segment_id",
    "indices": "index_id",
}
_NAMED = re.compile(r"(?<![:\w]):([a-zA-Z_]\w*)")          # :name  (not ::cast)
_COLLATE = re.compile(r"([\w.]+)\s*=\s*(%\([a-zA-Z_]\w*\)s|%s)\s+COLLATE\s+NOCASE", re.I)
_QMARK = re.compile(r"(?<!\w)\?(?!\w)")
_INSERT_TABLE = re.compile(r"INSERT\s+(?:OR\s+IGNORE\s+)?INTO\s+(\w+)", re.I)


def env_url() -> str | None:
    return os.environ.get("FINQA_PG_URL") or os.environ.get("DATABASE_URL")


def _translate(sql: str) -> str:
    sql = _NAMED.sub(r"%(\1)s", sql)
    sql = _QMARK.sub("%s", sql)
    sql = _COLLATE.sub(r"\1 ILIKE \2", sql)
    if re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO", sql, re.I):
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.I)
        if "on conflict" not in sql.lower():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    # give back a primary key where the SQLite code will read cursor.lastrowid
    m = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, re.I)
    if m and "returning" not in sql.lower():
        pk = _PK_BY_TABLE.get(m.group(1).lower())
        if pk:
            sql = sql.rstrip().rstrip(";") + f" RETURNING {pk}"
    return sql


class _Row(dict):
    """dict row that also supports positional access (row[0])."""

    __slots__ = ("_vals",)

    def __init__(self, pairs):
        pairs = list(pairs)
        super().__init__(pairs)
        object.__setattr__(self, "_vals", [v for _, v in pairs])

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    cols = [c.name for c in (cursor.description or [])]
    return lambda values: _Row(zip(cols, values))


class _PgCursor:
    def __init__(self, cur):
        self._cur = cur
        self.lastrowid = None
        if cur.description and cur.rowcount != 0:
            try:
                first = cur.fetchone()
            except psycopg.ProgrammingError:
                first = None
            self._buffer = [first] if first is not None else []
            if first is not None and len(first) == 1:
                self.lastrowid = first[0]
        else:
            self._buffer = []

    def fetchone(self):
        if self._buffer:
            return self._buffer.pop(0)
        return self._cur.fetchone()

    def fetchall(self):
        rest = self._cur.fetchall()
        out, self._buffer = self._buffer + list(rest), []
        return out

    def __iter__(self):
        return iter(self.fetchall())


class _PgConn:
    """Minimal sqlite3.Connection-shaped adapter over a psycopg3 connection."""

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor(row_factory=_row_factory)
        cur.execute(_translate(sql), params if params is not None else None)
        return _PgCursor(cur)

    def executescript(self, sql: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


# --------------------------------------------------------------------------- #

def connect_pg(url: str | None = None) -> psycopg.Connection:
    url = url or env_url()
    if not url:
        raise RuntimeError("no Postgres URL (set FINQA_PG_URL or DATABASE_URL)")
    return psycopg.connect(url, autocommit=False, row_factory=dict_row)


def init_pg(conn: _PgConn) -> None:
    conn.executescript(_SCHEMA.read_text(encoding="utf-8"))


class PgRepositories:
    """Same surface as `SqliteRepositories`, backed by PostgreSQL + pgvector."""

    def __init__(self, url: str | None = None) -> None:
        self._raw = connect_pg(url)
        self._conn = _PgConn(self._raw)
        init_pg(self._conn)
        self.companies = SqliteCompanyRepository(self._conn)
        self.indices = SqliteIndexRepository(self._conn)
        self.sources = SqliteSourceRepository(self._conn)
        self.facts = SqliteFinancialFactRepository(self._conn)
        self.segments = SqliteSegmentRepository(self._conn)
        self.prices = SqliteSharePriceRepository(self._conn)
        self.documents = SqliteDocumentRepository(self._conn)

    @property
    def connection(self):
        return self._conn

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PgRepositories":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._conn.commit()
        self._conn.close()
