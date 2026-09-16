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

# Run as an unprivileged user (§26) -- see api.Dockerfile's comment. This one still
# needs write access to the bind-mounted database/data/ and data_extraction/data/
# (docker-compose.yml mounts those read-write for this service specifically), which
# works because those are host bind mounts, not container-owned paths -- there's
# nothing under /app itself for this container to write to.
RUN groupadd -r finqa && useradd -r -g finqa -d /app finqa && chown -R finqa:finqa /app
USER finqa

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "finqa_v2.dataset.build"]
