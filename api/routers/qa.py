"""POST /qa, POST /companies/{symbol}/qa -- natural-language financial QA,
delegating straight to qa_router's own answer_question() (Stage 10/11): the
same classify -> route -> {financial engine | peer/ranking engine | RAG |
LLM} pipeline the `finqa` CLI already uses, over the same long-lived
AnalysisBridge/RagBridge subprocesses this app starts once at startup (see
api/main.py's lifespan) -- not a new pair per request, matching how the
CLI's own interactive mode reuses one pair across questions.

This is the one route where an LLM (Groq/Anthropic via llm_router, or
nothing if unconfigured) may contribute to the answer text -- and per
qa.py's own design, only ever as an interpretation layer over already-
verified retrieval/engine output. It never invents the underlying numbers;
see qa.py's `caveats`/`warnings` fields, passed through unchanged below."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.qa import answer_question

from api.deps import (
    get_analysis_bridge, get_db_path, get_rag_bridge, rate_limit_qa, require_api_key, resolve_company,
)
from api.models import QARequest, QAResponse

router = APIRouter(tags=["qa"], dependencies=[Depends(require_api_key), Depends(rate_limit_qa)])


@router.post("/qa", response_model=QAResponse)
def ask_question(
    body: QARequest,
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
    rag_bridge=Depends(get_rag_bridge),
) -> dict:
    return answer_question(body.question, db_path=db_path, analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)


@router.post("/companies/{symbol}/qa", response_model=QAResponse)
def ask_question_about_company(
    symbol: str,
    body: QARequest,
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
    rag_bridge=Depends(get_rag_bridge),
) -> dict:
    """Same as POST /qa, but pins the question's company resolution to
    `symbol` (via answer_question's companies_override) instead of relying
    on qa_router's own name/alias matching against the question text --
    useful when the caller already knows which company a UI panel is
    scoped to and doesn't want a misclassified/ambiguous match."""
    company = resolve_company(symbol, db_path)
    return answer_question(
        body.question, db_path=db_path, analysis_bridge=analysis_bridge, rag_bridge=rag_bridge,
        companies_override=[company["symbol"]],
    )