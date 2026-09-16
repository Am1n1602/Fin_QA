"""Query decomposition (§13): split a comparison / multi-company-causal question into
retrieval-only sub-questions, fanned out via §9's multi-query retrieval
(`finqa_v2/reasoning/orchestrator.py`'s `_tool_calls()` issues one `search_documents`
call per sub-question instead of one for the combined question). §13's own scoping rule:
"Only decompose queries classified as comparison, multi_hop, complex causal. Do not
invoke decomposition for simple factual queries" -- `decompose()` returns `[]` (no
decomposition) for every other intent, and the orchestrator falls back to searching
`plan.question` as a single query exactly as before when `[]` comes back.

Sub-questions are RETRIEVAL-ONLY: they never replace or bypass the deterministic
Financial Engine's own tool-routed numeric answers (§4's core principle) -- they only
change what `search_documents` searches for.
"""
from __future__ import annotations

import re

from finqa_v2.planner.models import Intent, QueryPlan

_COMPARATIVE = re.compile(r"\bcompar(e|ed|ison)\b|\bversus\b|\bvs\.?\b", re.I)


def decompose(plan: QueryPlan) -> list[str]:
    metric = plan.metrics[0].replace("_", " ") if plan.metrics else "performance"

    if plan.intent is Intent.COMPARISON and len(plan.companies) >= 2:
        return [f"{co} {metric}" for co in plan.companies]

    if (plan.intent is Intent.CAUSAL and len(plan.companies) >= 2
            and _COMPARATIVE.search(plan.question)):
        primary = plan.companies[0]
        return [f"why did {primary} {metric} change"] + [f"{co} {metric}" for co in plan.companies]

    return []
