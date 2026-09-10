"""Query Planner (§20): question -> structured execution plan. LLM-backed with a
deterministic rules fallback. See docs/file-guide.md."""
from __future__ import annotations

from .models import Intent, QueryPlan
from .planner import QueryPlanner
from .rules import plan_with_rules

__all__ = ["Intent", "QueryPlan", "QueryPlanner", "plan_with_rules"]
