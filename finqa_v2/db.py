"""One place to get a repository bundle. `repositories_from_env()` returns the
PostgreSQL backend when `FINQA_PG_URL` / `DATABASE_URL` is set, else SQLite -- so
production vs. dev is an env var, not a code change (§7 / §17)."""
from __future__ import annotations

import os
from pathlib import Path


def repositories_from_env(*, sqlite_path: str | Path | None = None, check_same_thread: bool = True):
    """PgRepositories if a Postgres URL is in the environment, otherwise
    SqliteRepositories. Both satisfy the `finqa_v2.repositories` Protocols.

    `check_same_thread` only affects the SQLite path -- pass False for a server that
    answers each request on a different worker thread from one connection built at
    startup (see finqa_v2/sqlite/repo.py's `_ThreadSafeConnection`); PgRepositories'
    connection is always thread-safe internally, so it ignores this flag."""
    url = os.environ.get("FINQA_PG_URL") or os.environ.get("DATABASE_URL")
    if url:
        from finqa_v2.postgres import PgRepositories

        return PgRepositories(url)
    from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

    return SqliteRepositories(sqlite_path or DEFAULT_V2_DB_PATH, check_same_thread=check_same_thread)
