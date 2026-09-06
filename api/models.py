"""
api/models.py -- request bodies only.

Deliberately no response models for engine output. The analysis engine
(data_analysis, reached via AnalysisBridge) and qa_router's own qa.py already
define and document their own JSON shapes.
Route handlers return plain dict/list bodies
built directly from the engine's own output; FastAPI serializes those as-is.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FilingType = Literal["consolidated", "standalone"]


class QARequest(BaseModel):
    question: str = Field(..., min_length=1, description="A natural-language financial question.")


class QAResponse(BaseModel):
    question: str
    intent: str
    classification: dict
    answer: str
    data: dict
    sources: list
    warnings: list
    caveats: list