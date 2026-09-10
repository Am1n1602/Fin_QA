"""build_default_registry -- every §19 tool wired to the v2 engine / repos / retriever."""
from __future__ import annotations

from database.v2.tools import company, documents, financial, math_tools
from database.v2.tools.base import ToolRegistry

_FINANCIAL = ("get_metric", "get_ratio", "get_growth", "get_cagr", "compare_companies",
              "compare_periods", "get_segment_data", "decompose_metric")
_DOCUMENT = ("search_documents", "get_document_section", "get_source")
_MATH = ("calculate",)
_COMPANY = ("get_company", "get_peers", "get_index_members")

ALL_TOOLS = _FINANCIAL + _DOCUMENT + _MATH + _COMPANY


def build_default_registry(repos, *, engine=None, retriever=None) -> ToolRegistry:
    """`engine` defaults to a FinancialEngine over `repos`. `retriever` is optional --
    document search raises a clear error until one is wired."""
    if engine is None:
        from database.v2.engine import FinancialEngine

        engine = FinancialEngine(repos)

    reg = ToolRegistry()
    financial.register(reg, engine)
    documents.register(reg, repos, retriever)
    math_tools.register(reg)
    company.register(reg, repos)
    return reg
