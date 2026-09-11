# finqa_v2 worker -- runs the dataset-rebuild / retrieval-index-rebuild jobs on demand
# or via `docker compose run`. Same install as the API image, different entrypoint.
# There's no task queue in this project today (no Celery/RQ) -- this is an
# independently-deployable container for the same one-shot management commands the
# CLI already runs (finqa_v2.dataset.build, finqa_v2.retrieval.build_indexes, ...),
# not a standing background service.
#
# Examples:
#   docker compose run --rm worker python -m finqa_v2.dataset.build --skip-docs
#   docker compose run --rm worker python -m finqa_v2.retrieval.build_indexes
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY finqa_v2/ ./finqa_v2/

# CPU-only torch -- see api.Dockerfile's comment; this container has no GPU either.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[anthropic]"

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "finqa_v2.dataset.build"]
