from __future__ import annotations

from fastapi import APIRouter, Depends

from src.qa import answer_question

from api import config as api_config
from api.deps import get_analysis_bridge, get_db_path, get_rag_bridge, require_api_key, resolve_company
from api.models import QARequest, QAResponse

router = APIRouter(tags=["qa"], dependencies=[Depends(require_api_key)])


@router.post("/qa", response_model=QAResponse)
def ask_question(
    body: QARequest,
    db_path: str = Depends(get_db_path),
    analysis_bridge=Depends(get_analysis_bridge),
    rag_bridge=Depends(get_rag_bridge),
) -> dict:
    return answer_question(
        body.question, db_path=db_path, analysis_bridge=analysis_bridge, rag_bridge=rag_bridge,
        rag_bridge_disabled=api_config.RAG_DISABLED,
    )


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
        companies_override=[company["symbol"]], rag_bridge_disabled=api_config.RAG_DISABLED,
    )