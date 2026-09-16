"""Shared test doubles: no network, no real LLM."""
from __future__ import annotations

from finqa_v2.models import DocumentChunk


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, payload: str = "The available figures answer this question."):
        self._payload = payload
        self.usage = {"requests_made": 0, "total_tokens": 0}
        self.calls: list[dict] = []

    def complete(self, prompt, *, system=None, temperature=0.1, max_tokens=1024, json_object=False):
        self.usage["requests_made"] += 1
        self.calls.append({"prompt": prompt, "system": system})
        return self._payload


class FakeRetriever:
    modes = ("lexical", "vector", "hybrid")

    def __init__(self, chunks: list[DocumentChunk] | None = None):
        self._chunks = chunks if chunks is not None else [
            DocumentChunk(document_id=1, company_id=1, chunk_index=0,
                         text="TCS revenue in FY2026 was 2,670,210,000,000 INR.",
                         page_start=4, page_end=4, section="financial_results"),
        ]

    def retrieve(self, query, *, k=5, candidate_k=30, mode="hybrid", filters=None, rerank=True):
        import types

        return [types.SimpleNamespace(chunk=c, rank=i + 1, scores={"lexical": 1.0})
               for i, c in enumerate(self._chunks[:k])]


class EmptyRetriever(FakeRetriever):
    def __init__(self):
        super().__init__(chunks=[])
