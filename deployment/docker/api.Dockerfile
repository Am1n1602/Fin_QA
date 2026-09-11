# finqa_v2 API -- build from the repo root:
#   docker build -f deployment/docker/api.Dockerfile -t finqa-api-v2 .
# Only finqa_v2/ + pyproject.toml are copied in: archive/ (v1) isn't needed to serve
# the API, and isn't present in the build context (see .dockerignore) -- setuptools'
# packages.find simply finds no `archive*` packages to include, which is fine.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY finqa_v2/ ./finqa_v2/

# CPU-only torch: the default PyPI wheel pulls the full NVIDIA CUDA runtime (several
# GB of libraries this container, with no GPU, will never use) -- installing torch
# from PyTorch's own CPU wheel index first means pip never considers the CUDA build.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[api,anthropic]"

ENV PYTHONUNBUFFERED=1 \
    FINQA_V2_API_HOST=0.0.0.0 \
    FINQA_V2_API_PORT=8010

EXPOSE 8010

# database/data/ (SQLite fallback + the BM25/vector retrieval index files, which live
# outside Postgres either way) is mounted as a volume at runtime -- see docker-compose.yml.
CMD ["uvicorn", "finqa_v2.api.main:app", "--host", "0.0.0.0", "--port", "8010"]
