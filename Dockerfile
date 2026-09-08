FROM python:3.11-slim

WORKDIR /app

# faiss-cpu / sentence-transformers / torch wheels are available as manylinux
# wheels for this base image, but a C build toolchain is kept anyway since a
# pip resolver fallback to a source build (e.g. a torch version without a
# prebuilt wheel for this Python/arch combo) would otherwise fail opaquely.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -e ".[api]"

RUN test -f data/demo/finqa.db || \
        (echo "ERROR: data/demo/finqa.db not found -- run build_demo_corpus.py first." && exit 1)
RUN mkdir -p database/data rag/data/indices \
    && cp data/demo/finqa.db database/data/financial_intelligence.db \
    && rm -f rag/data/indices/*.faiss rag/data/indices/manifest.json \
    && cp data/demo/faiss/*.faiss rag/data/indices/ \
    && cp data/demo/faiss/manifest.json rag/data/indices/manifest.json

ENV PYTHONUNBUFFERED=1
ENV FINQA_MODE=demo

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]