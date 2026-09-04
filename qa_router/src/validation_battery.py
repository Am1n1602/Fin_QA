"""
Usage:
    cd qa_router
    python -m src.validation_battery                    # full battery
    python -m src.validation_battery --no-llm            # deterministic-only, free
    python -m src.validation_battery --no-rag-probe       # skip the isolated retrieval probe
    python -m src.validation_battery --limit 10           # first 10 questions only
    python -m src.validation_battery --db-path ... --data-analysis-dir ... --rag-dir ...

Writes a timestamped JSON with full results + latency percentiles to
qa_router/stage12d_validation_outputs/ (same convention as Stage 11's
stage11_validation_outputs/), and prints a human-readable summary.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from src.bridges.analysis_bridge import AnalysisBridge
from src.bridges.rag_bridge import RagBridge
from src.config import DATA_ANALYSIS_DIR, DB_PATH, DEVICE, EMBEDDING_MODEL_NAME, RAG_DIR, RAG_INDEX_DIR, \
    RERANK_MODEL_NAME
from src.qa import answer_question

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

OUT_DIR = Path(__file__).resolve().parent.parent / "stage12d_validation_outputs"

QUESTIONS: list[dict] = [

    {"q": "What is TCS's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is AXISBANK's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is HDFCBANK's revenue?", "expect_intent": "numeric_fact"},
    {"q": "What is SBILIFE's net profit?", "expect_intent": "numeric_fact"},
    {"q": "What is BAJFINANCE's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is BAJAJFINSV's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is BAJAJ-AUTO's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is M&M's revenue?", "expect_intent": "numeric_fact"},
    {"q": "What is RELIANCE's ROE?", "expect_intent": "numeric_fact"},
    {"q": "What is INFY's EPS?", "expect_intent": "numeric_fact"},

    {"q": "What is the trend in TCS's revenue over the last few years?", "expect_intent": "trend"},
    {"q": "How has HDFCBANK's net profit growth changed historically?", "expect_intent": "trend"},
    {"q": "What is ICICIBANK's YoY growth?", "expect_intent": "trend"},

    # comparison
    {"q": "Compare TCS and INFY's ROE.", "expect_intent": "comparison"},
    {"q": "HDFCBANK vs ICICIBANK vs AXISBANK ROE", "expect_intent": "comparison"},
    {"q": "Which company has the highest revenue: RELIANCE or TCS?", "expect_intent": "comparison"},

    {"q": "Rank the strongest companies by fundamentals.", "expect_intent": "ranking"},
    {"q": "Which is the best company by overall score?", "expect_intent": "ranking"},

    # financial_health
    {"q": "What is TCS's Piotroski F-Score?", "expect_intent": "financial_health"},
    {"q": "Is HDFCBANK financially healthy?", "expect_intent": "financial_health"},


    {"q": "Generate a full report for TCS.", "expect_intent": "report"},

    # narrative -- RAG retrieval + one Groq call, no numeric signal
    {"q": "What does the filing say about AXISBANK's outlook?", "expect_intent": "narrative"},
    {"q": "Discuss HDFCBANK's risk factors mentioned in the filing.", "expect_intent": "narrative"},

    {"q": "Why has AXISBANK's ROE declined?", "expect_intent": "complex"},
    {"q": "Why did TCS's net profit grow over the last few years?", "expect_intent": "complex"},

    {"q": "What is NOTAREALTICKER's ROE?", "expect_intent": "unknown"},
    {"q": "Tell me about the weather.", "expect_intent": "unknown"},
]

RAG_PROBE_COMPANIES = [
    "TCS", "AXISBANK", "HDFCBANK", "SBILIFE", "BAJFINANCE",
    "RELIANCE", "INFY", "BAJAJ-AUTO",
]
RAG_PROBE_QUERY = "What does management say about the company's outlook and performance?"


def _percentiles(latencies: list[float]) -> dict:
    if not latencies:
        return {}
    sorted_l = sorted(latencies)
    out = {
        "count": len(sorted_l),
        "min_s": round(sorted_l[0], 3),
        "max_s": round(sorted_l[-1], 3),
        "mean_s": round(statistics.mean(sorted_l), 3),
        "median_s": round(statistics.median(sorted_l), 3),
    }
    if len(sorted_l) >= 5:
        out["p95_s"] = round(statistics.quantiles(sorted_l, n=20)[18], 3)
    return out


def run_battery(
    db_path: str, data_analysis_dir: str, rag_dir: str, index_dir: str, model_name: str,
    rerank_model: str, device: str, limit: int | None, no_llm: bool, no_rag_probe: bool,
) -> dict:
    questions = QUESTIONS[:limit] if limit else QUESTIONS
    if no_llm:
        questions = [q for q in questions if q["expect_intent"] not in ("narrative", "complex")]

    print(f"Loading AnalysisBridge + RagBridge once for this whole run ({len(questions)} questions)...")
    t_load0 = time.perf_counter()
    analysis_bridge = AnalysisBridge(db_path=db_path, data_analysis_dir=data_analysis_dir)
    rag_bridge = RagBridge(db_path=db_path, rag_dir=rag_dir, index_dir=index_dir,
                            model_name=model_name, rerank_model=rerank_model, device=device)
    construct_time_s = time.perf_counter() - t_load0
    print(f"Bridges constructed (not yet started -- both are lazy) in {construct_time_s:.2f}s.")

   

    print("Warming up AnalysisBridge (forces subprocess start + imports)...")
    t_warm_analysis0 = time.perf_counter()
    analysis_bridge.warm_up()
    analysis_warmup_s = time.perf_counter() - t_warm_analysis0
    print(f"  AnalysisBridge warm-up: {analysis_warmup_s:.2f}s")

    print("Warming up RagBridge (forces subprocess start + embedder + reranker load)...")
    t_warm_rag0 = time.perf_counter()
    rag_bridge.warm_up()
    rag_warmup_s = time.perf_counter() - t_warm_rag0
    print(f"  RagBridge warm-up: {rag_warmup_s:.2f}s")

    load_time_s = time.perf_counter() - t_load0
    print(f"Total setup (construct + both warm-ups): {load_time_s:.2f}s -- Stage 11's per-question "
          f"subprocess pattern paid a comparable cost on EVERY question; this run pays it exactly once, "
          f"up front, accounted for separately from any question's own latency below.")

    results: list[dict] = []
    rag_probe_results: list[dict] = []
    try:
        for i, item in enumerate(questions, 1):
            q = item["q"]
            print(f"[{i}/{len(questions)}] {q}")
            t0 = time.perf_counter()
            try:
                r = answer_question(q, db_path=db_path, analysis_bridge=analysis_bridge, rag_bridge=rag_bridge)
                elapsed = time.perf_counter() - t0
                results.append({
                    "question": q,
                    "expected_intent": item["expect_intent"],
                    "actual_intent": r["intent"],
                    "intent_match": r["intent"] == item["expect_intent"],
                    "elapsed_s": round(elapsed, 3),
                    "companies": r["classification"]["companies"],
                    "metrics": r["classification"]["metrics"],
                    "answer_preview": r["answer"][:300],
                    "warnings": r.get("warnings", []),
                    "error": None,
                })
                print(f"    -> intent={r['intent']}  {elapsed:.2f}s")
            except Exception as e:  # noqa: BLE001 -- per-question isolation is the point, see module docstring
                elapsed = time.perf_counter() - t0
                results.append({
                    "question": q,
                    "expected_intent": item["expect_intent"],
                    "actual_intent": None,
                    "intent_match": False,
                    "elapsed_s": round(elapsed, 3),
                    "companies": [],
                    "metrics": [],
                    "answer_preview": None,
                    "warnings": [],
                    "error": f"{type(e).__name__}: {e}",
                })
                print(f"    -> ERROR after {elapsed:.2f}s: {type(e).__name__}: {e}")
                traceback.print_exc(file=sys.stderr)

        if not no_rag_probe:
            print(f"\nIsolated RAG-retrieval-only probe ({len(RAG_PROBE_COMPANIES)} companies, "
                  f"no LLM call, pure FAISS+cross-encoder timing)...")
            for company in RAG_PROBE_COMPANIES:
                t0 = time.perf_counter()
                try:
                    chunks = rag_bridge.reranked_retrieve(RAG_PROBE_QUERY, k=5, company=company)
                    elapsed = time.perf_counter() - t0
                    rag_probe_results.append({
                        "company": company, "elapsed_s": round(elapsed, 3),
                        "chunks_returned": len(chunks or []), "error": None,
                    })
                    print(f"    {company}: {elapsed:.2f}s, {len(chunks or [])} chunks")
                except Exception as e:  # noqa: BLE001
                    elapsed = time.perf_counter() - t0
                    rag_probe_results.append({
                        "company": company, "elapsed_s": round(elapsed, 3),
                        "chunks_returned": 0, "error": f"{type(e).__name__}: {e}",
                    })
                    print(f"    {company}: ERROR after {elapsed:.2f}s: {e}")
    finally:
        analysis_bridge.close()
        rag_bridge.close()

    ok_results = [r for r in results if r["error"] is None]
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "bridge_construct_time_s": round(construct_time_s, 3),
        "analysis_bridge_warmup_s": round(analysis_warmup_s, 3),
        "rag_bridge_warmup_s": round(rag_warmup_s, 3),
        "bridge_load_time_s": round(load_time_s, 3),  # construct + both warm-ups, for backward-compat with the 12d run
        "questions_run": len(questions),
        "results": results,
        "rag_probe_results": rag_probe_results,
        "latency_all": _percentiles([r["elapsed_s"] for r in ok_results]),
        "latency_by_intent": {
            intent: _percentiles([r["elapsed_s"] for r in ok_results if r["actual_intent"] == intent])
            for intent in sorted({r["actual_intent"] for r in ok_results if r["actual_intent"]})
        },
        "rag_probe_latency": _percentiles([r["elapsed_s"] for r in rag_probe_results if r["error"] is None]),
        "intent_mismatches": [r for r in ok_results if not r["intent_match"]],
        "errors": [r for r in results if r["error"] is not None],
    }


def _print_summary(summary: dict) -> None:
    print("\n" + "=" * 70)
    print("STAGE 12d VALIDATION BATTERY -- SUMMARY")
    print("=" * 70)
    print(f"Bridge construct: {summary['bridge_construct_time_s']}s  "
          f"| AnalysisBridge warm-up: {summary['analysis_bridge_warmup_s']}s  "
          f"| RagBridge warm-up: {summary['rag_bridge_warmup_s']}s  "
          f"| total setup: {summary['bridge_load_time_s']}s")
    print(f"Questions run: {summary['questions_run']}")
    print(f"Errors (uncaught exceptions): {len(summary['errors'])}")
    print(f"Intent mismatches (vs. this battery's own expectation): {len(summary['intent_mismatches'])}")
    print(f"\nOverall latency, successful questions: {summary['latency_all']}")
    print("\nLatency by actual intent:")
    for intent, stats in summary["latency_by_intent"].items():
        print(f"  {intent}: {stats}")
    if summary["rag_probe_latency"]:
        print(f"\nIsolated RAG retrieval latency (no LLM involved): {summary['rag_probe_latency']}")
    if summary["errors"]:
        print("\nErrors:")
        for e in summary["errors"]:
            print(f"  - {e['question']!r}: {e['error']}")
    if summary["intent_mismatches"]:
        print("\nIntent mismatches (informational -- this battery's own guess at the 'right' intent")
        print("may itself be wrong; treat as a prompt to look, not a confirmed classify.py bug):")
        for m in summary["intent_mismatches"]:
            print(f"  - {m['question']!r}: expected {m['expected_intent']}, got {m['actual_intent']}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--data-analysis-dir", default=str(DATA_ANALYSIS_DIR))
    parser.add_argument("--rag-dir", default=str(RAG_DIR))
    parser.add_argument("--index-dir", default=str(RAG_INDEX_DIR))
    parser.add_argument("--model-name", default=EMBEDDING_MODEL_NAME)
    parser.add_argument("--rerank-model", default=RERANK_MODEL_NAME)
    parser.add_argument("--device", default=DEVICE)
    parser.add_argument("--limit", type=int, default=None, help="Cap the number of battery questions run")
    parser.add_argument("--no-llm", action="store_true",
                         help="Skip narrative/complex questions entirely -- fast, free, deterministic-only pass")
    parser.add_argument("--no-rag-probe", action="store_true",
                         help="Skip the isolated RAG-retrieval-only latency probe")
    parser.add_argument("--out-dir", default=str(OUT_DIR))
    args = parser.parse_args()

    summary = run_battery(
        db_path=args.db_path, data_analysis_dir=args.data_analysis_dir, rag_dir=args.rag_dir,
        index_dir=args.index_dir, model_name=args.model_name, rerank_model=args.rerank_model,
        device=args.device, limit=args.limit, no_llm=args.no_llm, no_rag_probe=args.no_rag_probe,
    )
    _print_summary(summary)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"validation_{stamp}.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()