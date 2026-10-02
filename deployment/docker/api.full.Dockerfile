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

# Files are owned by `finqa` at COPY time (--chown) instead of a trailing `chown -R /app`:
# that recursive chown writes a second copy of every file under /app into a new layer,
# which here doubled the dataset -- a 1.98GB extra layer to build, store and upload.
RUN groupadd -r finqa && useradd -r -g finqa -d /app finqa \
    && mkdir -p /app && chown finqa:finqa /app

WORKDIR /app

COPY --chown=finqa:finqa pyproject.toml ./
COPY --chown=finqa:finqa finqa_v2/ ./finqa_v2/
COPY --chown=finqa:finqa evaluation/regression/baselines/ ./evaluation/regression/baselines/
COPY --chown=finqa:finqa deployment/docker/full_data/finqa_v2.db deployment/docker/full_data/finqa_v2_bm25.pkl ./database/data/
COPY --chown=finqa:finqa deployment/docker/full_data/finqa_v2_vec ./database/data/finqa_v2_vec/

# CPU-only torch -- see api.Dockerfile's identical comment. This image actually needs
# it at runtime (unlike api.public.Dockerfile): finqa_v2_vec/ is present, so
# build_retriever() imports SentenceTransformerEmbedder/VectorIndex/faiss for real.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[api,anthropic,observability]"

# Bake the actual embedding model weights into the image instead of fetching them from
# huggingface.co on every cold start. Cloud Run containers are ephemeral -- with no
# baked cache, SentenceTransformerEmbedder (finqa_v2/retrieval/embed.py) re-downloads
# the model from the Hub on EVERY new instance, and this was observed in production to
# actually break the service, not just slow it down: Hugging Face rate-limited those
# repeated requests (HTTP 429, "Rate limited. Waiting 200.0s before retry"), which blew
# past Cloud Run's startup probe timeout, so the instance was killed before it ever
# came up -- and the next request just triggered another instance that failed the same
# way, forever. HF_HOME must match where the `finqa` user's HOME resolves the default
# cache to, and HF_HUB_OFFLINE=1 (set below, at runtime only) guarantees no request to
# huggingface.co is ever attempted again regardless.
ENV HF_HOME=/app/.cache/huggingface
USER finqa
RUN python -c "from finqa_v2.retrieval.embed import SentenceTransformerEmbedder; SentenceTransformerEmbedder('all-MiniLM-L6-v2').encode(['warm'])"

ENV PYTHONUNBUFFERED=1 \
    FINQA_V2_API_HOST=0.0.0.0 \
    FINQA_V2_API_PORT=8010 \
    HF_HUB_OFFLINE=1

EXPOSE 8010

CMD ["uvicorn", "finqa_v2.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
