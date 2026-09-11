"""Request bodies only -- deliberately no response models. Every response is the tool's
own JSON-safe value dict (see deps.call_tool) or the §31 research-response schema; both
are already documented at their source (finqa_v2/tools/, finqa_v2/evidence/graph.py).
See docs/file-guide.md.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Basis = Literal["consolidated", "standalone"]


class QARequest(BaseModel):
    question: str = Field(..., min_length=1, description="A natural-language financial question.")
    use_llm: bool = Field(True, description="False forces the deterministic (no-LLM) synthesis path.")
