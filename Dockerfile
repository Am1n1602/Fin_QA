FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -e ".[api]"

RUN test -f demo_dataset/finqa.db || \
        (echo "ERROR: demo_dataset/finqa.db not found -- run build_demo_corpus.py first and git add/commit/push its output." && exit 1)
RUN mkdir -p database/data rag/data/indices \
    && cp demo_dataset/finqa.db database/data/financial_intelligence.db \
    && rm -f rag/data/indices/*.faiss rag/data/indices/manifest.json \
    && cp demo_dataset/faiss/*.faiss rag/data/indices/ \
    && cp demo_dataset/faiss/manifest.json rag/data/indices/manifest.json

ENV PYTHONUNBUFFERED=1
ENV FINQA_MODE=demo
ENV FINQA_DISABLE_RAG=true

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]