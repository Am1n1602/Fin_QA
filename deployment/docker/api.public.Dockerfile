# finqa_v2 API -- PUBLIC DEMO variant. Build from the repo root, AFTER running
#   python deployment/scripts/build_public_dataset.py
# (regenerates deployment/docker/public_data/, which this Dockerfile copies in):
#   docker build -f deployment/docker/api.public.Dockerfile -t finqa-api-public .
#
# Differs from api.Dockerfile in two ways, both driven by "no persistent disk, no live
# ingestion" on the free hosting tiers this targets (Render free Web Service):
#
# 1. Bakes in a read-only dataset snapshot instead of expecting a bind-mounted volume.
#    It's a CURATED subset of companies (deployment/scripts/build_public_dataset.py), not
#    the full 50-company finqa_v2.db -- a first pass baking in the full dataset measured
#    ~680MB resident memory in a running container (almost all of it rank_bm25's
#    per-document term-frequency dicts for the full 32k-chunk corpus), well over a
#    typical free tier's ~512MB ceiling. The curated subset's BM25 index is a fraction of
#    that size. See build_public_dataset.py's own docstring and deployment/README.md's
#    "Public demo (Render)" section for the measured-after number -- re-measure with
#    `docker stats` after ever changing the curated ticker list, don't assume it still fits.
#
# 2. No dense/hybrid retrieval: finqa_v2/retrieval/evaluate.py's build_retriever() only
#    imports SentenceTransformerEmbedder/VectorIndex/faiss at all `if
#    vector_dir.exists()`, so simply not baking in a finqa_v2_vec/ directory means torch
#    is never imported at runtime -- avoiding the exact OOM failure mode that killed the
#    abandoned demo-v1 branch on the same free-tier class of host. Lexical-only BM25
#    remains, which this project's own Phase 16/27 measurements show is competitive with
#    hybrid on this dataset anyway.
#
# No FINQA_PG_URL is set, so the app falls back to the baked-in SQLite file
# (finqa_v2/db.py:repositories_from_env()) -- no Postgres needed either.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY finqa_v2/ ./finqa_v2/
COPY evaluation/regression/baselines/ ./evaluation/regression/baselines/
COPY deployment/docker/public_data/finqa_v2.db deployment/docker/public_data/finqa_v2_bm25.pkl ./database/data/

# CPU-only torch -- see api.Dockerfile's identical comment. Installed even though this
# image never imports it (no vector_dir present, see above) so this Dockerfile doesn't
# have to fork pyproject.toml's dependency list; the unused wheel costs build/disk time,
# not runtime memory, since it's never `import torch`-ed.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[api,anthropic,observability]"

RUN groupadd -r finqa && useradd -r -g finqa -d /app finqa && chown -R finqa:finqa /app
USER finqa

ENV PYTHONUNBUFFERED=1 \
    FINQA_V2_API_HOST=0.0.0.0 \
    FINQA_V2_API_PORT=8010

EXPOSE 8010

CMD ["uvicorn", "finqa_v2.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
