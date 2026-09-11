"""Request bodies only -- deliberately no response models. Every response is the tool's
own JSON-safe value dict (see deps.call_tool) or the §31 research-response schema; both
are already documented at their source (finqa_v2/tools/, finqa_v2/evidence/graph.py).
See docs/file-guide.md.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Basis = Literal["consolidated", "standalone"]

# Generous for any real financial question; caps what an LLM-touching request can embed
# in a prompt (cost) and rejects an oversized payload before it reaches the orchestrator.
_MAX_QUESTION_LENGTH = 2000


class QARequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)   # so a whitespace-only string can't slip past min_length

    question: str = Field(..., min_length=1, max_length=_MAX_QUESTION_LENGTH,
                          description="A natural-language financial question.")
    use_llm: bool = Field(True, description="False forces the deterministic (no-LLM) synthesis path.")
