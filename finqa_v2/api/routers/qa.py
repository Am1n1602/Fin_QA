"""POST /api/v2/qa -- free-form natural-language financial QA: the full research
architecture (planner + Financial Engine + hybrid RAG + calculator + reasoning +
verification, §21/§27), returning the sanitised §31 response + claim graph. The one route
where an LLM may contribute (per its own design, only as an interpretation layer over
already-verified engine/retrieval output -- see finqa_v2/reasoning/synthesize.py's SYSTEM
prompt); it never invents the underlying numbers."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from finqa_v2.api.deps import get_orchestrator, rate_limit_qa
from finqa_v2.api.models import QARequest
from finqa_v2.api.sanitize import strip_server_paths

# API-key enforcement is global (security_middleware, main.py) -- this router only adds
# its OWN, much stricter rate limit on top, since an LLM call here has real cost/latency.
router = APIRouter(prefix="/api/v2/qa", tags=["qa"], dependencies=[Depends(rate_limit_qa)])


@router.post("")
def ask(body: QARequest, orchestrator=Depends(get_orchestrator)):
    result = orchestrator.answer(body.question, use_llm=body.use_llm, claim_graph_reachable_only=True)
    return strip_server_paths(result.to_dict())
