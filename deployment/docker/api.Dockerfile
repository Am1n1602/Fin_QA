# finqa_v2 API -- build from the repo root:
#   docker build -f deployment/docker/api.Dockerfile -t finqa-api-v2 .
# Only finqa_v2/ + pyproject.toml are copied in: archive/ (v1) isn't needed to serve
# the API, and isn't present in the build context (see .dockerignore) -- setuptools'
# packages.find simply finds no `archive*` packages to include, which is fine.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY finqa_v2/ ./finqa_v2/
# Just the pinned baseline JSON (not the rest of evaluation/) -- /metrics' eval-monitoring
# gauges read this; see finqa_v2/api/config.py's FINQA_V2_EVAL_BASELINE_PATH.
COPY evaluation/regression/baselines/ ./evaluation/regression/baselines/

# CPU-only torch: the default PyPI wheel pulls the full NVIDIA CUDA runtime (several
# GB of libraries this container, with no GPU, will never use) -- installing torch
# from PyTorch's own CPU wheel index first means pip never considers the CUDA build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[api,anthropic,observability]"

# Run as an unprivileged user (§26) -- the process serves untrusted HTTP input all day;
# root inside a container is still a real privilege-escalation surface if any dependency
# in this fairly large install ever has a container-breakout bug. Created after pip
# install so the install itself (writing into /usr/local) still runs as root.
RUN groupadd -r finqa && useradd -r -g finqa -d /app finqa && chown -R finqa:finqa /app
USER finqa

ENV PYTHONUNBUFFERED=1 \
    FINQA_V2_API_HOST=0.0.0.0 \
    FINQA_V2_API_PORT=8010

EXPOSE 8010

# database/data/ (SQLite fallback + the BM25/vector retrieval index files, which live
# outside Postgres either way) is mounted as a volume at runtime -- see docker-compose.yml.
CMD ["uvicorn", "finqa_v2.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
