"""ReasoningOrchestrator (§21, §27): PLAN -> RETRIEVE/CALCULATE -> INSPECT -> REASON -> ANSWER.

Single bounded pass over the plan's tools (no re-plan loop yet). Every tool call is
traced. With no LLM provider the whole thing still returns a §31 response, built from
evidence by the deterministic synthesizer.
"""
from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from finqa_v2.claimgraph import ClaimGraphView
from finqa_v2.crossval import CrossValidator
from finqa_v2.evidence import ClaimGraph, Evidence, EvidenceSet
from finqa_v2.evidence.models import Calculation
from finqa_v2.hypothesis import HypothesisTester
from finqa_v2.llm import LLMBudgetExceededError, LLMError, NullProvider
from finqa_v2.planner import QueryPlanner
from finqa_v2.planner.models import Intent
from finqa_v2.reasoning.models import ReasoningResult
from finqa_v2.reasoning.synthesize import (
    SYSTEM,
    build_prompt,
    deterministic_answer,
    parse_synthesis,
)
from finqa_v2.tools import build_default_registry
from finqa_v2.verification import Verifier

_UNIVERSE_CAP = 12


class ReasoningOrchestrator:
    def __init__(self, repos, *, planner=None, registry=None, provider=None,
                 retriever=None, engine=None, max_tools: int = 6):
        self._repos = repos
        self._provider = provider or NullProvider()
        if engine is None:
            from finqa_v2.engine import FinancialEngine

            engine = FinancialEngine(repos)
        self._engine = engine
        self._retriever = retriever
        self._registry = registry or build_default_registry(repos, engine=engine, retriever=retriever)
        self._planner = planner or QueryPlanner(repos, registry=self._registry, provider=self._provider)
        self._max_tools = max_tools
        self._hypothesis = HypothesisTester(repos, engine=engine, retriever=retriever,
                                            provider=self._provider)
        self._crossval = CrossValidator(repos, engine=engine, retriever=retriever,
                                        provider=self._provider)
        self._verifier = Verifier()

    # ------------------------------------------------------------------ #
    def answer(self, question: str, *, use_llm: bool = True,
              claim_graph_reachable_only: bool = False) -> ReasoningResult:
        t0 = perf_counter()
        self._registry.reset_trace()
        plan = self._planner.plan(question, use_llm=use_llm)

        ws = EvidenceSet()
        graph = ClaimGraph(ws)
        tools_run: list[str] = []

        universe = None
        for name, args in self._tool_calls(plan):
            if len(tools_run) >= self._max_tools:
                break
            if name == "compare_companies" and len(args.get("tickers", [])) < 2:
                universe = universe if universe is not None else self._resolve_universe(plan)
                args["tickers"] = universe
                if len(universe) < 2:
                    continue
            res = self._registry.call(name, **args)
            tools_run.append(name)
            if not res.ok:
                continue
            for ed in res.evidence:
                ws.add(Evidence.from_dict(ed))
            if isinstance(res.value, dict) and isinstance(res.value.get("calculation"), dict):
                graph.add_calculation(Calculation.from_dict(res.value["calculation"]))

        kind, report = self._run_deep_analysis(question, plan, ws, graph, use_llm)

        answer, limitations, llm_used = self._reason(question, plan, ws, graph, use_llm, report)
        response = graph.to_response(answer, limitations=limitations)
        # §25: verify verbatim figures only when the answer is a direct restatement of the
        # workspace -- Phase 11/12 verdict prose carries derived figures, not fact values.
        verification = self._verifier.verify(response, ws, graph=graph,
                                             check_numbers=kind is None)
        # §24, Phase-22: reachable_only=True (the public API's choice) drops evidence/
        # sources no claim actually cites, so a causal answer's response doesn't dump the
        # entire ~48-node reasoning workspace.
        claim_graph = ClaimGraphView(graph).to_dict(reachable_only=claim_graph_reachable_only)
        return ReasoningResult(
            question=question, plan=plan.to_dict(), response=response,
            trace=[asdict(c) for c in self._registry.trace],
            tools_run=tools_run, llm_used=llm_used,
            latency_ms=(perf_counter() - t0) * 1000,
            hypothesis_report=report.to_dict() if kind == "hypothesis" else None,
            cross_validation_report=report.to_dict() if kind == "cross_validation" else None,
            verification=verification.to_dict(),
            claim_graph=claim_graph,
        )

    # ------------------------------------------------------------------ #
    def _run_deep_analysis(self, question, plan, ws, graph, use_llm):
        """§22 HYPOTHESIZE / §23 cross-validate -- needs a named company. -> (kind, report)."""
        if not plan.companies:
            return None, None
        if plan.intent is Intent.CAUSAL:
            metric = plan.metrics[0] if plan.metrics else "net_profit"
            rep = self._hypothesis.run(question, plan.companies[0], metric,
                                       workspace=ws, use_llm=use_llm)
            for h in rep.hypotheses:
                graph.add_claim(h.statement, kind="causal",
                                evidence_ids=h.support_evidence_ids, status=h.status)
            return "hypothesis", rep
        if plan.intent is Intent.CROSS_VALIDATION:
            rep = self._crossval.validate(question, plan.companies[0], plan_metrics=plan.metrics,
                                          workspace=ws, use_llm=use_llm)
            if rep.claim is not None:
                graph.add_claim(rep.claim.raw, kind="cross_validation",
                                evidence_ids=rep.support_evidence_ids, status=rep.status)
            return "cross_validation", rep
        return None, None

    # ------------------------------------------------------------------ #
    def _reason(self, question, plan, ws, graph, use_llm, report=None):
        analysis_block = report.render() if report is not None else None
        parsed = None
        if use_llm and not isinstance(self._provider, NullProvider) and len(ws):
            try:
                raw = self._provider.complete(
                    build_prompt(question, plan, ws, analysis=analysis_block), system=SYSTEM,
                    json_object=True, temperature=0.1, max_tokens=900,
                )
                parsed = parse_synthesis(raw, {e.evidence_id for e in ws})
            except (LLMError, LLMBudgetExceededError):
                parsed = None
        if parsed is None:
            parsed = deterministic_answer(question, plan, ws, analysis=report)
            llm_used = False
        else:
            llm_used = True
        for c in parsed["claims"]:
            graph.add_claim(c["text"], kind=c["kind"], evidence_ids=c["evidence_ids"])
        limitations = parsed["limitations"]
        if report is not None:
            for lim in report.limitations:
                if lim not in limitations:
                    limitations.append(lim)
        return parsed["answer"], limitations, llm_used

    # ------------------------------------------------------------------ #
    def _resolve_universe(self, plan) -> list[str]:
        if len(plan.companies) >= 2:
            return plan.companies
        if plan.companies:
            r = self._registry.call("get_peers", ticker=plan.companies[0])
            if r.ok:
                return ([plan.companies[0]] + [p["ticker"] for p in r.value["peers"]])[:_UNIVERSE_CAP]
        r = self._registry.call("get_index_members", index_name="NIFTY 50")
        if r.ok:
            return [c["ticker"] for c in r.value["members"]][:_UNIVERSE_CAP]
        return list(plan.companies)

    def _tool_calls(self, plan):
        """Yield (tool_name, kwargs) for each tool the plan asks for, with args derived
        from the plan. Tools that can't be satisfied from the plan are skipped."""
        co = plan.companies[0] if plan.companies else None
        metric = plan.metrics[0] if plan.metrics else None
        period = plan.periods[0] if plan.periods else "latest"

        for name in plan.tools:
            if name == "get_metric" and co:
                yield name, {"ticker": co, "metric": metric or "revenue", "period": period}
            elif name == "get_ratio" and co:
                yield name, {"ticker": co, "ratio": metric or "roe", "period": period}
            elif name == "get_growth" and co:
                yield name, {"ticker": co, "metric": metric or "revenue", "kind": "yoy"}
            elif name == "get_cagr" and co:
                yield name, {"ticker": co, "metric": metric or "revenue"}
            elif name == "compare_companies":
                m = metric or ("roe" if plan.intent is Intent.RANKING else "revenue")
                yield name, {"metric": m, "tickers": list(plan.companies)}
            elif name == "compare_periods" and co and len(plan.periods) >= 2:
                yield name, {"ticker": co, "metrics": plan.metrics or ["revenue", "net_profit"],
                             "a": plan.periods[0], "b": plan.periods[1]}
            elif name == "get_segment_data" and co:
                yield name, {"ticker": co, "period": "latest_annual"}
            elif name == "decompose_metric" and co:
                dm = "roe" if (metric in (None, "roe", "roce", "roa")) else "net_margin"
                yield name, {"ticker": co, "metric": dm}
            elif name == "search_documents":
                a = {"query": plan.question, "k": 5}
                if len(plan.companies) == 1:
                    a["company"] = co
                yield name, a
            elif name == "get_company" and co:
                yield name, {"ticker": co}
            elif name == "get_peers" and co:
                yield name, {"ticker": co}
