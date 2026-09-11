# deployment/ — Fin_QA v2 (§33, §47)

Phase 17 scope was the **PostgreSQL + pgvector** backend alone. Phase 24 scope is the
rest: every piece of finqa_v2 (API, dashboard, database, object storage, a worker,
the LLM provider) as its own independently deployable container.

## Full local stack (Phase 24)

```bash
cd deployment/compose
docker compose up -d --build postgres minio minio-init api dashboard
```

This starts, as separate containers on one Docker network:

| Service | What it is | Host port |
|---|---|---|
| `postgres` | PostgreSQL + pgvector (the database) | 55432 → 5432 |
| `minio` | S3-compatible object storage (filing PDFs) | 9000 (API), 9001 (console) |
| `minio-init` | One-shot: creates the `filing-pdfs` bucket, then exits | — |
| `api` | `finqa_v2` FastAPI app, talking to `postgres` over the compose network | 8010 |
| `dashboard` | `dashboard_v2`, built static and served by nginx | 5174 |

`GROQ_API_KEY`/`ANTHROPIC_API_KEY` are read from your shell environment (or a `.env`
file in `deployment/compose/`, which `docker compose` loads automatically) and passed
into the `api` container.

### One-time: load data into the containerized Postgres

The `postgres` container starts empty. Load it from your existing local `finqa_v2.db`
(run from the repo root, using your normal dev venv — not inside a container):

```bash
export FINQA_PG_URL=postgresql://finqa:finqa@localhost:55432/finqa   # Windows: set FINQA_PG_URL=...
python -m finqa_v2.postgres.migrate
```

Re-run any time the local `finqa_v2.db` changes — `migrate` truncates and refills every
table (idempotent) and reloads `document_chunks.embedding` from
`database/data/finqa_v2_vec/matrix.npy`.

### Verify

```bash
curl http://localhost:8010/health
open http://localhost:5174        # or just browse there
```

### The worker (dataset rebuild, on demand)

Not started by `up` — there's no task queue in this project (no Celery/RQ), so "worker"
here means the same one-shot management commands the CLI already runs, packaged as
their own container instead of requiring a local Python environment:

```bash
docker compose run --rm worker python -m finqa_v2.dataset.build --skip-docs
docker compose run --rm worker python -m finqa_v2.retrieval.build_indexes
```

The worker mounts `database/data/` and `data_extraction/data/` read-write (the `api`
container mounts `database/data/` read-only — it never writes to the dataset).

### Object storage: syncing filing PDFs

```bash
pip install boto3   # or: pip install -e ".[storage]"
python deployment/scripts/sync_pdfs_to_object_storage.py \
    --endpoint-url http://localhost:9000 --access-key finqa --secret-key finqa12345
```

Uploads every PDF under `data_extraction/data/raw/<TICKER>/` into the `filing-pdfs`
bucket (skips ones already there). This gives the filing PDFs a second, network-
reachable home; `finqa_v2/documents/backfill.py` still reads them from local disk
during ingestion — pointing ingestion at object storage instead is a natural next
step, not done here, since the local-disk path is the well-tested one today.

### Tearing down

```bash
docker compose down            # stop containers, keep volumes (Postgres/MinIO data)
docker compose down -v         # also delete the named volumes
```

## PostgreSQL + pgvector alone (Phase 17, still works standalone)

```bash
docker compose -f deployment/compose/pgvector.yml up -d
export FINQA_PG_URL=postgresql://finqa:finqa@localhost:55432/finqa   # Windows: set FINQA_PG_URL=...
```

Everything else is unchanged — the repository Protocols (`finqa_v2/repositories.py`) are
the only contract. `finqa_v2.db.repositories_from_env()` returns `PgRepositories` when
`FINQA_PG_URL` (or `DATABASE_URL`) is set, else `SqliteRepositories`; `finqa_v2/api/main.py`'s
lifespan calls this directly, so switching backends for the API is an env var, not a
code change.

```bash
python -m finqa_v2.postgres.migrate
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
- `_PgConn` (like SQLite's `_ThreadSafeConnection`) serializes every `execute()` behind
  a lock and fully materializes each result set before releasing it — a single shared
  psycopg3 connection, like a single shared sqlite3 connection, is not safe for
  concurrent use across FastAPI's thread-pooled request handlers otherwise. Fixed
  ahead of Phase 24 specifically because this phase is the first time the API actually
  runs against Postgres under real concurrent load.
- `document_chunks.embedding vector(384)` + an `ivfflat` cosine index. Retrieval can move
  off the file-based faiss index to `PgVectorIndex` (`finqa_v2/postgres/pgvector_index.py`)
  which implements the same `.search()` / `.available` surface `HybridRetriever` expects.
- `deployment/docker/*.Dockerfile` build from the repo root as their context (so they
  can `COPY finqa_v2/` etc.) — always `docker build -f deployment/docker/X.Dockerfile .`
  from the repo root, or use the compose file, which already sets `context: ../..`.
