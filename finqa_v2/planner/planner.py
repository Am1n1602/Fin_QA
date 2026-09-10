"""QueryPlanner facade (§20). LLM plan when a provider is wired and returns valid JSON;
deterministic rules plan otherwise. Always returns a valid QueryPlan.
"""
from __future__ import annotations

from finqa_v2.llm import LLMBudgetExceededError, LLMError, LLMProvider, NullProvider
from finqa_v2.planner.models import Intent, QueryPlan
from finqa_v2.planner.prompt import build_prompt, parse_plan
from finqa_v2.planner.rules import CompanyMatcher, plan_with_rules


class QueryPlanner:
    def __init__(self, repos, *, registry=None, provider: LLMProvider | None = None):
        self._repos = repos
        self._matcher = CompanyMatcher(repos)
        self._provider = provider or NullProvider()
        if registry is None:
            from finqa_v2.tools import build_default_registry

            registry = build_default_registry(repos)
        self._catalog = [(s["name"], s["description"]) for s in registry.schemas()]
        self._valid_tools = {n for n, _ in self._catalog}
        self._tickers = [c.ticker for c in repos.companies.list(active=True)]
        self._valid_tickers = set(self._tickers)

    # ------------------------------------------------------------------ #
    def plan(self, question: str, *, use_llm: bool = True) -> QueryPlan:
        rules_plan = plan_with_rules(question, matcher=self._matcher)
        if not use_llm or isinstance(self._provider, NullProvider):
            return rules_plan
        try:
            raw = self._provider.complete(
                build_prompt(question, tool_catalog=self._catalog, known_tickers=self._tickers),
                system=None, json_object=True, temperature=0.0, max_tokens=700,
            )
        except LLMBudgetExceededError as e:
            rules_plan.notes.append(f"llm budget exhausted; used rules ({e})")
            return rules_plan
        except LLMError:
            rules_plan.notes.append("llm planner unavailable; used rules")
            return rules_plan
        llm_plan = parse_plan(question, raw, valid_tools=self._valid_tools,
                              valid_tickers=self._valid_tickers)
        if llm_plan is None:
            rules_plan.notes.append("llm plan unparseable; used rules")
            return rules_plan
        return self._merge(llm_plan, rules_plan)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _merge(llm: QueryPlan, rules: QueryPlan) -> QueryPlan:
        """§44 finding: the LLM reads intent/entities better than rules, but the
        deterministic mapping picks tools more reliably. So keep the LLM's
        intent / companies / periods / metrics (backfilling obvious misses from
        rules), then derive tools from the deterministic intent->tools mapping."""
        from finqa_v2.planner.rules import _tools_for

        if not llm.companies:
            llm.companies = rules.companies
        if not llm.metrics:
            llm.metrics = rules.metrics
        if not llm.periods:
            llm.periods = rules.periods
        if llm.intent is Intent.UNKNOWN and rules.intent is not Intent.UNKNOWN:
            llm.intent = rules.intent
        if not llm.sub_questions:
            llm.sub_questions = rules.sub_questions

        mapped_tools, needs_docs, needs_calc = _tools_for(llm.intent, llm.metrics)
        llm_extras = [t for t in llm.tools if t == "search_documents"]  # LLM may flag a doc need
        llm.tools = mapped_tools + [t for t in llm_extras if t not in mapped_tools]
        llm.needs_documents = llm.needs_documents or needs_docs or ("search_documents" in llm.tools)
        llm.needs_calculation = llm.needs_calculation or needs_calc
        llm.notes = llm.notes + [n for n in rules.notes if n not in llm.notes]
        llm.__post_init__()
        return llm
