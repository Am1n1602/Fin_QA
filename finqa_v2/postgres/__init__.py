"""PostgreSQL + pgvector backend (§7 / §17). Same repository Protocols as the SQLite
backend -- the engine / tools / reasoning / retrieval code is unchanged. See
docs/file-guide.md and deployment/README.md.

No re-export here on purpose: `psycopg` is an optional dependency (the `postgres` extra
in pyproject.toml), and this package's own `__init__.py` running is exactly what
`unittest discover`'s package walk triggers just to reach `finqa_v2/postgres/tests/`,
regardless of whether anything actually needs Postgres -- confirmed 2026-09-27 as the
real cause of a CI failure after `psycopg` became optional (the eager
`from .repo import ...` here made `import finqa_v2.postgres` itself fail with no
`psycopg` installed, well before any skip-gated test got a chance to run). Import
directly from `finqa_v2.postgres.repo` instead, and only where `psycopg` is guaranteed
installed (both real call sites already do this lazily: `finqa_v2/db.py` behind a
`FINQA_PG_URL` check, `postgres/tests/test_postgres.py` behind its own skip guard)."""
from __future__ import annotations
