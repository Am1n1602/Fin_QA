"""PostgreSQL + pgvector backend (§7 / §17). Same repository Protocols as the SQLite
backend -- the engine / tools / reasoning / retrieval code is unchanged. See
docs/file-guide.md and deployment/README.md."""
from __future__ import annotations

from .repo import PgRepositories, connect_pg, env_url, init_pg

__all__ = ["PgRepositories", "connect_pg", "env_url", "init_pg"]
