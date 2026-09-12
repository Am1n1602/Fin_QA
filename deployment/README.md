# deployment/ — Fin_QA v2 (§33, §47)

Phase 17 scope was the **PostgreSQL + pgvector** backend alone. Phase 24 scope was the
rest of the architecture (API, dashboard, database, object storage, a worker, the LLM
provider) as its own independently deployable container. Phase 25 scope is
**observability**: metrics, structured logs with request-id correlation, cost/failure
tracking, and eval-baseline monitoring, all exported from the running `api` container.

## Full local stack (Phase 24 + 25)

```bash
cd deployment/compose
docker compose up -d --build postgres minio minio-init api dashboard prometheus grafana
```

This starts, as separate containers on one Docker network:

| Service | What it is | Host port |
|---|---|---|
| `postgres` | PostgreSQL + pgvector (the database) | 55432 → 5432 |
| `minio` | S3-compatible object storage (filing PDFs) | 9000 (API), 9001 (console) |
| `minio-init` | One-shot: creates the `filing-pdfs` bucket, then exits | — |
| `api` | `finqa_v2` FastAPI app, talking to `postgres` over the compose network | 8010 |
| `dashboard` | `dashboard_v2`, built static and served by nginx | 5174 |
| `prometheus` | Scrapes `api`'s `/metrics` every 15s | 9090 |
| `grafana` | Pre-provisioned "Fin·QA v2 — Overview" dashboard over Prometheus | 3000 (see below for the admin password) |

`GROQ_API_KEY`/`ANTHROPIC_API_KEY` are read from your shell environment (or a `.env`
file in `deployment/compose/`, which `docker compose` loads automatically) and passed
into the `api` container.

**Grafana, Postgres, and MinIO all have no default password.** Copy
`deployment/compose/.env.example` to `deployment/compose/.env` and set
`GRAFANA_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, and `MINIO_ROOT_PASSWORD` before running
`docker compose up` — without any one of them, `docker compose` fails fast with a clear
error naming the missing variable instead of starting that service with a guessable
password (`finqa`/`finqa12345` used to be baked into this file; they no longer are).
Usernames/DB name (`GRAFANA_ADMIN_USER`, `POSTGRES_USER`, `POSTGRES_DB`,
`MINIO_ROOT_USER`) default to `admin`/`finqa`/`finqa`/`finqa` if left unset — only the
passwords are required. (Grafana anonymous access was also tried in Phase 25 and
removed — see the Phase 25 write-up in `docs/file-guide.md` — so a real login is
required there either way.)

### One-time: load data into the containerized Postgres

The `postgres` container starts empty. Load it from your existing local `finqa_v2.db`
(run from the repo root, using your normal dev venv — not inside a container), using the
same `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB` you set in `.env`:

```bash
export FINQA_PG_URL=postgresql://finqa:<POSTGRES_PASSWORD>@localhost:55432/finqa   # Windows: set FINQA_PG_URL=...
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
    --endpoint-url http://localhost:9000 --access-key finqa --secret-key <MINIO_ROOT_PASSWORD>
```

Uploads every PDF under `data_extraction/data/raw/<TICKER>/` into the `filing-pdfs`
bucket (skips ones already there). This gives the filing PDFs a second, network-
reachable home; `finqa_v2/documents/backfill.py` still reads them from local disk
during ingestion — pointing ingestion at object storage instead is a natural next
step, not done here, since the local-disk path is the well-tested one today.

### Observability (Phase 25)

```bash
curl http://localhost:8010/metrics     # raw Prometheus exposition format
open http://localhost:9090             # Prometheus UI -- query finqa_* metrics directly
open http://localhost:3000             # Grafana -- "Fin QA" folder, "Fin·QA v2 — Overview" dashboard
```

What's exported, and where each number actually comes from (nothing here is a separate
estimate -- every metric is written from a choke point the rest of the system already
runs through):

| Metric | Written from |
|---|---|
| `finqa_http_requests_total`, `finqa_http_request_duration_seconds` | the API's own request middleware, labelled by route **template** (`/api/v2/companies/{ticker}`, not the real ticker) so per-company traffic doesn't explode the label cardinality |
| `finqa_tool_calls_total`, `finqa_tool_call_duration_seconds` | `ToolRegistry.call()` (§19) -- every deterministic answer and every LLM-planned tool call passes through here |
| `finqa_llm_requests_total`, `finqa_llm_tokens_total`, `finqa_llm_cost_usd_total` | `RateBudget.record()` (Groq) / `CostBudget.record()` (Anthropic) -- the same accounting the free-tier/cost-cap guards themselves use |
| `finqa_verification_status_total` | `Verifier.verify()`'s own `passed` / `passed_with_warnings` / `abstained` verdict |
| `finqa_eval_baseline_accuracy`, `finqa_eval_baseline_info` | the pinned regression-gate baseline (`evaluation/regression/baselines/deterministic_v2.json`), re-read from disk on every `/metrics` scrape -- reflects the last time someone ran the eval + regression gate and updated the pinned baseline, **not** a continuously-running live eval |

Structured logs (`finqa_v2/observability/logging_config.py`) tag every log line with the
same `request_id` for the request that produced it (also returned as the `X-Request-ID`
response header) -- this is Phase 25's "tracing" for a single-service deployment: grep one
id to see a request's path across the API, the Tool Registry, and the LLM provider,
without standing up a separate distributed-tracing backend a system this size doesn't
need. Set `FINQA_V2_LOG_JSON=1` (already set for the `api` container) for one JSON object
per line instead of plain text.

### Tearing down

```bash
docker compose down            # stop containers, keep volumes (Postgres/MinIO data)
docker compose down -v         # also delete the named volumes
```

## PostgreSQL + pgvector alone (Phase 17, still works standalone)

Needs the same `POSTGRES_PASSWORD` (in `deployment/compose/.env`, see `.env.example`) as
the full stack above — this compose file is picked up from the same directory.

```bash
docker compose -f deployment/compose/pgvector.yml up -d
export FINQA_PG_URL=postgresql://finqa:<POSTGRES_PASSWORD>@localhost:55432/finqa   # Windows: set FINQA_PG_URL=...
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

## Public demo (Render)

A separate, deliberately smaller deployment target for an actual public URL — two free
Render services, defined in `render.yaml` at the repo root. This is **not** the same
stack as the sections above: no Postgres, no MinIO, no Prometheus/Grafana, and no dense
retrieval, all for the same underlying reason (a free host has no persistent disk and
limited RAM, and this system's normal retrieval path pulls in torch).

**What's different from the local stack, and why:**

- **A curated ~10-15 company subset, not all 50.** `deployment/scripts/build_public_dataset.py`
  copies a chosen ticker list out of the real `finqa_v2.db` into
  `deployment/docker/public_data/` (gitignored, rebuild locally any time). A first attempt
  baked in the *full* 50-company dataset and measured **~680MB** resident memory in the
  running container — almost entirely `rank_bm25`'s per-document term-frequency
  dictionaries for the full 32k-chunk corpus — comfortably over a typical free tier's
  ~512MB ceiling. The current 12-company set (`TCS, INFY, HCLTECH, WIPRO, RELIANCE, ONGC,
  HDFCBANK, ICICIBANK, SBIN, ITC, M&M, SBILIFE` — picked for sector diversity and so every
  example question in this README and the dashboard's own example chips resolves)
  measured **~250-320MB** resident / ~490MB including reclaimable page cache. **Always
  re-measure with `docker stats` + `docker exec <container> cat /proc/1/status` after
  changing `TICKERS`** — this is empirical, not something to assume scales safely.
- **Lexical-only retrieval, no torch loaded at all.** `deployment/docker/api.public.Dockerfile`
  bakes in `finqa_v2.db` + `finqa_v2_bm25.pkl` but not `finqa_v2_vec/` (the dense vector
  index). `finqa_v2/retrieval/evaluate.py`'s `build_retriever()` only imports
  `SentenceTransformerEmbedder`/`VectorIndex`/faiss `if vector_dir.exists()` — so omitting
  that directory means `torch` is never imported at runtime (verified: `python -c "import
  sys; print('torch' in sys.modules)"` inside the running container prints `False`), which
  is what actually avoids the OOM failure mode that killed the abandoned `demo-v1` branch
  on this same class of free host. This costs dense/hybrid retrieval, not much else —
  Phase 16/27's own measurements found lexical competitive with hybrid on this dataset.
- **SQLite, no Postgres.** `finqa_v2/db.py:repositories_from_env()` already falls back to
  `SqliteRepositories` with no `FINQA_PG_URL` set — nothing to configure.
- **Two independent Render services, not one.** A free *static site* never sleeps; a free
  *web service* does (spins down after inactivity, ~30-60s cold start on the next
  request). Splitting them means the dashboard shell loads instantly and only the API
  needs a "waking up" experience — `dashboard_v2/src/components/WakeGate.jsx` polls
  `GET /health` and shows a friendly wait screen until the API answers, instead of the
  app rendering with everything failing.

**Deploy flow:**

```bash
# 1. Build the curated dataset + image, push it to a registry (needs your own
#    `docker login ghcr.io` first — this step isn't run for you, it needs your account)
deployment/scripts/build_and_push_public_image.sh ghcr.io/YOUR_GITHUB_USERNAME/finqa-api-public:latest

# 2. Edit render.yaml's image.url to match what you just pushed.

# 3. In the Render dashboard: New -> Blueprint -> connect this repo -> it creates
#    finqa-api-public (from the image) and finqa-dashboard-public (built from
#    dashboard_v2/ source, auto-redeploys on push) from render.yaml.

# 4. Set GROQ_API_KEY on finqa-api-public in the Render dashboard (marked `sync: false`
#    in render.yaml specifically so it's never in git).
```

Re-run step 1 (which re-runs `build_public_dataset.py` first) whenever the curated
dataset should be refreshed from a newer local `finqa_v2.db` — this deploy target is a
frozen snapshot, not a live pipeline, same "historical depth" caveat as the rest of the
project.

**Not covered by CI.** `.github/workflows/ci.yml` runs the test suites and the regression
gate; it does not build or push the public image — that stays a manual step (it needs
registry credentials this repo's CI doesn't have configured, and the dataset shouldn't be
rebuilt on every commit anyway).

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
- `PgRepositories` connects with `autocommit=True` (Phase 25). Unlike sqlite3, psycopg3
  under `autocommit=False` opens an implicit transaction for every statement, reads
  included — a long-lived connection (the API) that never explicitly commits after a
  read leaves that transaction open indefinitely, observed as an `idle in transaction`
  session blocking an unrelated `DROP SCHEMA` elsewhere. `migrate.py` connects directly
  via `connect_pg()` (not through `PgRepositories`) to keep its own bulk copy atomic, so
  it's unaffected by this.
- `document_chunks.embedding vector(384)` + an `ivfflat` cosine index. Retrieval can move
  off the file-based faiss index to `PgVectorIndex` (`finqa_v2/postgres/pgvector_index.py`)
  which implements the same `.search()` / `.available` surface `HybridRetriever` expects.
- `deployment/docker/*.Dockerfile` build from the repo root as their context (so they
  can `COPY finqa_v2/` etc.) — always `docker build -f deployment/docker/X.Dockerfile .`
  from the repo root, or use the compose file, which already sets `context: ../..`.
