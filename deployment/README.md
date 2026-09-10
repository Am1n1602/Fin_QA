# deployment/ — Fin_QA v2 (§33, §47)

Phase 17 scope: the **PostgreSQL + pgvector** backend. The query-serving and ingestion
paths stay independently deployable; this dir holds the DB piece.

## PostgreSQL + pgvector (dev / staging)

```bash
docker compose -f deployment/compose/pgvector.yml up -d
export FINQA_PG_URL=postgresql://finqa:finqa@localhost:55432/finqa   # Windows: set FINQA_PG_URL=...
```

Everything else is unchanged — the repository Protocols (`finqa_v2/repositories.py`) are
the only contract. `finqa_v2.db.repositories_from_env()` returns `PgRepositories` when
`FINQA_PG_URL` (or `DATABASE_URL`) is set, else `SqliteRepositories`.

### One-time data load

```bash
python -m finqa_v2.postgres.migrate        # SQLite finqa_v2.db -> PG, PKs preserved, + embeddings
```

`migrate` TRUNCATEs and refills every table (idempotent), applies `schema_pg.sql` first,
then loads `database/data/finqa_v2_vec/matrix.npy` into `document_chunks.embedding`.

### Verify

```bash
FINQA_PG_URL=... python -m finqa_v2.dataset.audit          # runs on PG unchanged
FINQA_PG_URL=... python -m unittest finqa_v2.postgres.tests.test_postgres
```

The gated test suite skips itself when `FINQA_PG_URL` is unset.

## Notes

- Dates/datetimes are stored as ISO **TEXT** and booleans as **INTEGER 0/1** — identical
  to the SQLite schema — so the row→model mappers and `_ds/_d/_b` helpers are shared and
  the repository *logic* is literally the SQLite classes fed a psycopg3 connection
  adapter (`finqa_v2/postgres/repo.py:_PgConn`). Only the SQL dialect is rewritten
  (`:name`→`%(name)s`, `?`→`%s`, `COLLATE NOCASE`→`ILIKE`, `RETURNING <pk>` for
  `lastrowid`).
- `document_chunks.embedding vector(384)` + an `ivfflat` cosine index. Retrieval can move
  off the file-based faiss index to `PgVectorIndex` (`finqa_v2/postgres/pgvector_index.py`)
  which implements the same `.search()` / `.available` surface `HybridRetriever` expects.
- Production (§33): managed Postgres + pgvector, object storage for the PDFs, a separate
  ingestion worker. Not in this phase.
