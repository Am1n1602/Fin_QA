"""GET /api/v2/companies/{ticker}/research -- a canned research-overview question through
the full reasoning pipeline (planner + engine + hybrid RAG + reasoning + verification),
same as POST /qa but scoped to one company. Rate-limited like /qa -- an LLM may run."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from finqa_v2.api.deps import (
    get_orchestrator,
    get_repos,
    rate_limit_qa,
    resolve_company,
)
from finqa_v2.api.sanitize import strip_server_paths

# API-key enforcement is global (security_middleware, main.py) -- this router only adds
# its OWN, much stricter rate limit on top, since an LLM call here has real cost/latency.
router = APIRouter(prefix="/api/v2/companies/{ticker}/research", tags=["research"],
                    dependencies=[Depends(rate_limit_qa)])


@router.get("")
def research(
    ticker: str,
    use_llm: bool = Query(True, description="False forces the deterministic (no-LLM) synthesis path."),
    repos=Depends(get_repos),
    orchestrator=Depends(get_orchestrator),
):
    company = resolve_company(repos, ticker)
    question = f"Give a fundamental overview of {company.ticker}."
    result = orchestrator.answer(question, use_llm=use_llm, claim_graph_reachable_only=True)
    return strip_server_paths(result.to_dict())
