# finqa_v2 API -- FULL dataset variant, for a host with real memory (Cloud Run, a VM,
# etc.), not a ~512MB free tier. Build from the repo root, AFTER staging the complete
# dataset into deployment/docker/full_data/ (NOT gitignored-excluded like
# database/data/ itself -- see .dockerignore's comment on why api.public.Dockerfile
# uses the same staging-directory trick for its curated subset):
#
#   mkdir -p deployment/docker/full_data
#   cp database/data/finqa_v2.db database/data/finqa_v2_bm25.pkl deployment/docker/full_data/
#   cp -r database/data/finqa_v2_vec_minilm deployment/docker/full_data/finqa_v2_vec
#   docker build -f deployment/docker/api.full.Dockerfile -t finqa-api-full .
#
# Differs from api.public.Dockerfile in exactly the two ways that Dockerfile's own
# comment says the public demo deliberately gives up for a ~512MB free tier: this one
# bakes in the COMPLETE 50-company dataset (not a curated subset) and INCLUDES the
# vector index directory, so torch actually loads and hybrid (lexical + dense)
# retrieval is available, matching the local dev stack. Needs real memory to match --
# estimated at ~6-6.5GB resident for the full 261,479-chunk corpus, extrapolated from
# the public-demo curated-subset's measured chunk-count/memory ratio, NOT itself
# confirmed with `docker stats` against this exact image (see deployment/README.md's
# Cloud Run section). Deployed on Cloud Run at --memory 8Gi as headroom over that
# estimate; re-measure for real before shrinking the allocation.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY finqa_v2/ ./finqa_v2/
COPY evaluation/regression/baselines/ ./evaluation/regression/baselines/
COPY deployment/docker/full_data/finqa_v2.db deployment/docker/full_data/finqa_v2_bm25.pkl ./database/data/
COPY deployment/docker/full_data/finqa_v2_vec ./database/data/finqa_v2_vec/

# CPU-only torch -- see api.Dockerfile's identical comment. This image actually needs
# it at runtime (unlike api.public.Dockerfile): finqa_v2_vec/ is present, so
# build_retriever() imports SentenceTransformerEmbedder/VectorIndex/faiss for real.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[api,anthropic,observability]"

RUN groupadd -r finqa && useradd -r -g finqa -d /app finqa && chown -R finqa:finqa /app
USER finqa

ENV PYTHONUNBUFFERED=1 \
    FINQA_V2_API_HOST=0.0.0.0 \
    FINQA_V2_API_PORT=8010

EXPOSE 8010

CMD ["uvicorn", "finqa_v2.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
