"""Query-latency benchmark (§43): engine calls, retrieval, and the full deterministic
reasoning pipeline over a fixed query mix. No LLM (deterministic path), so latency is
reproducible and reflects the parts that scale with the dataset.
"""
from __future__ import annotations

import statistics as _st
from time import perf_counter

from finqa_v2.engine import FinancialEngine
from finqa_v2.reasoning import ReasoningOrchestrator

# (label, question, intent-ish) -- spans the §1 question taxonomy
_QUERIES = [
    ("numeric_fact", "What was TCS revenue in FY2026?"),
    ("ratio", "What was Infosys ROE in FY2026?"),
    ("valuation", "What is TCS P/E ratio?"),
    ("trend", "How has TCS revenue changed over the years?"),
    ("comparison", "Compare TCS and Infosys on ROE."),
    ("ranking", "Which IT companies have the strongest ROE?"),
    ("segment", "Which segment contributed most to Reliance's revenue growth?"),
    ("causal", "Why did HCLTECH profitability decline?"),
    ("cross_validation",
     "HCLTECH management highlighted margin expansion. Is this visible in the financial statements?"),
]

_ENGINE_CALLS = [
    ("get_metric", lambda e: e.get_metric("TCS", "revenue", period="latest_annual")),
    ("get_ratio", lambda e: e.get_ratio("TCS", "roe", period="latest_annual")),
    ("get_growth", lambda e: e.get_growth("TCS", "revenue", kind="yoy")),
    ("get_valuation", lambda e: e.get_ratio("TCS", "pe", period="latest_annual")),
    ("decompose_metric", lambda e: e.decompose_metric("TCS", "roe", period="latest_annual")),
    ("segment_growth", lambda e: e.segment_growth("RELIANCE")),
    ("compare_companies_4",
     lambda e: e.compare_companies("roe", ["TCS", "INFY", "HCLTECH", "WIPRO"])),
]


def _stats(xs_ms: list[float]) -> dict:
    xs = sorted(xs_ms)
    return {
        "n": len(xs),
        "mean_ms": round(_st.mean(xs), 2),
        "p50_ms": round(_st.median(xs), 2),
        "p95_ms": round(xs[min(len(xs) - 1, int(0.95 * len(xs)))], 2),
        "max_ms": round(xs[-1], 2),
    }


def _time(fn, repeats: int) -> list[float]:
    fn()  # warm-up (fills the engine's per-company record cache, etc.)
    out = []
    for _ in range(repeats):
        t = perf_counter()
        fn()
        out.append((perf_counter() - t) * 1000)
    return out


def benchmark_queries(repos, *, retriever=None, repeats: int = 8) -> dict:
    engine = FinancialEngine(repos)
    orch = ReasoningOrchestrator(repos, engine=engine, retriever=retriever)

    engine_bench = {}
    for label, call in _ENGINE_CALLS:
        try:
            engine_bench[label] = _stats(_time(lambda c=call: c(engine), repeats))
        except Exception as e:  # a company/metric absent in this dataset -> skip
            engine_bench[label] = {"error": f"{type(e).__name__}: {e}"}

    retrieval_bench = {}
    if retriever is not None:
        co = repos.companies.resolve("TCS")
        cid = co.company_id if co else None
        cases = [("lexical_nofilter", {"mode": "lexical", "filters": None}),
                 ("lexical_company", {"mode": "lexical",
                                      "filters": {"company_id": cid} if cid else None})]
        if "hybrid" in getattr(retriever, "modes", ()):
            cases.append(("hybrid_company", {"mode": "hybrid",
                                             "filters": {"company_id": cid} if cid else None}))
        q = "why did operating margin change and what drove revenue growth"
        for label, kw in cases:
            retrieval_bench[label] = _stats(_time(
                lambda kw=kw: retriever.retrieve(q, k=5, **kw), repeats))

    pipeline_bench = {}
    per_query = []
    for label, question in _QUERIES:
        try:
            samples = _time(lambda q=question: orch.answer(q, use_llm=False), max(3, repeats // 2))
            pipeline_bench[label] = _stats(samples)
            per_query.append({"label": label, "question": question,
                              "p50_ms": pipeline_bench[label]["p50_ms"]})
        except Exception as e:
            pipeline_bench[label] = {"error": f"{type(e).__name__}: {e}"}

    all_pipe = [v["p50_ms"] for v in pipeline_bench.values() if "p50_ms" in v]
    return {
        "repeats": repeats,
        "engine_calls_ms": engine_bench,
        "retrieval_ms": retrieval_bench,
        "pipeline_ms": pipeline_bench,
        "pipeline_overall": {
            "p50_of_p50_ms": round(_st.median(all_pipe), 2) if all_pipe else None,
            "max_p50_ms": round(max(all_pipe), 2) if all_pipe else None,
        },
        "per_query": per_query,
    }


def render(b: dict) -> str:
    lines = [f"latency benchmark (deterministic, {b['repeats']} repeats)"]
    lines.append("  engine calls (p50 / p95 ms):")
    for k, v in b["engine_calls_ms"].items():
        lines.append(f"    {k:20} {v.get('p50_ms', v.get('error', '?')):>8} / {v.get('p95_ms', '')}")
    if b["retrieval_ms"]:
        lines.append("  retrieval (p50 / p95 ms):")
        for k, v in b["retrieval_ms"].items():
            lines.append(f"    {k:20} {v['p50_ms']:>8} / {v['p95_ms']}")
    lines.append("  full pipeline, no LLM (p50 / p95 ms):")
    for k, v in b["pipeline_ms"].items():
        lines.append(f"    {k:20} {v.get('p50_ms', v.get('error', '?')):>8} / {v.get('p95_ms', '')}")
    o = b["pipeline_overall"]
    lines.append(f"  pipeline median p50 {o['p50_of_p50_ms']} ms | slowest query p50 {o['max_p50_ms']} ms")
    return "\n".join(lines)
