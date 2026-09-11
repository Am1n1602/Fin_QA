"""Phase 21 baseline experiments (§40): compare A (LLM-only) / B (Vector RAG) /
C (Financial Engine + LLM) / D (Full Fin_QA) on the same stratified question sample.

    python -m evaluation.baselines.runner --dataset evaluation/datasets/finqa_india.jsonl \
        --sample 15 --sample-seed 13 --llm

D reuses the real `ReasoningOrchestrator` unchanged; A/B/C are deliberately minimal
(no verification, no calculator, no evidence workspace beyond what each name implies) so
the comparison isolates what the full architecture adds. See docs/file-guide.md.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "evaluation" / "reports"
_DATA = ROOT / "database" / "data"
_DEFAULT_DB = _DATA / "finqa_v2.db"
_DEFAULT_BM25 = _DATA / "finqa_v2_bm25.pkl"
_DEFAULT_VEC = _DATA / "finqa_v2_vec"

BASELINES = ("A_llm_only", "B_vector_rag", "C_engine_llm", "D_full_finqa")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True).strip()
    except Exception:
        return "unknown"


def load_dataset(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def stratified_sample(records: list[dict], n: int, seed: int) -> list[dict]:
    if n >= len(records):
        return records
    rng = random.Random(seed)
    by_cat: dict[str, list[dict]] = {}
    for r in records:
        by_cat.setdefault(r.get("category", "?"), []).append(r)
    frac = n / len(records)
    picked: list[dict] = []
    for rows in by_cat.values():
        k = max(1, round(len(rows) * frac))
        picked.extend(rng.sample(rows, min(k, len(rows))))
    rng.shuffle(picked)
    return picked


def budget_split(names: list[str], total_cost_usd: float, spec: str | None) -> dict[str, float]:
    """Per-baseline $ caps: even split of `total_cost_usd` unless `spec` ('name:usd,...')
    overrides specific ones (e.g. weighting D higher -- it costs more per question)."""
    even = total_cost_usd / max(1, len(names))
    cap_for = {n: even for n in names}
    if spec:
        for part in spec.split(","):
            bname, _, amt = part.partition(":")
            if bname.strip() in cap_for:
                cap_for[bname.strip()] = float(amt)
    return cap_for


def _rate(rows: list[dict], key: str) -> dict:
    vs = [r["scores"].get(key, {}).get("verdict") for r in rows]
    p = sum(1 for v in vs if v == "pass")
    f = sum(1 for v in vs if v == "fail")
    return {"passed": p, "failed": f, "checked": p + f,
            "accuracy": round(p / (p + f), 4) if (p + f) else None}


def run_baseline(name: str, records: list[dict], *, repos, engine, retriever, provider,
                 evaluators, use_llm: bool) -> list[dict]:
    """Each baseline gets its OWN `provider` (and, for D, its own orchestrator) so a
    per-baseline dollar budget can't be starved by another baseline running first."""
    from evaluation.baselines.engine_llm import answer as answer_c
    from evaluation.baselines.llm_only import answer as answer_a
    from evaluation.baselines.vector_rag import answer as answer_b
    from evaluation.evaluators import score_record

    orchestrator = None
    if name == "D_full_finqa":
        from finqa_v2.reasoning import ReasoningOrchestrator

        orchestrator = ReasoningOrchestrator(repos, provider=provider, retriever=retriever,
                                             engine=engine)

    rows = []
    for rec in records:
        q = rec["question"]
        t0 = perf_counter()
        try:
            if name == "A_llm_only":
                result = answer_a(q, provider) if use_llm else _null(t0)
            elif name == "B_vector_rag":
                result = answer_b(q, retriever, repos, provider, k=5) if use_llm else _null(t0)
            elif name == "C_engine_llm":
                result = answer_c(q, repos, engine, provider) if use_llm else _null(t0)
            elif name == "D_full_finqa":
                result = orchestrator.answer(q, use_llm=use_llm).to_dict()
            else:
                raise ValueError(name)
            err = None
        except Exception as e:  # keep going; a broken baseline call is a data point too
            err = repr(e)
            result = _null(t0)
        rows.append({
            "id": rec["id"], "category": rec.get("category"), "question": q, "error": err,
            "answer": result["response"].get("answer", ""),
            "latency_ms": result.get("latency_ms", 0.0),
            "llm_used": result.get("llm_used", False),
            "scores": score_record(rec, result, evaluators),
        })
    return rows


def _null(t0) -> dict:
    return {"response": {"answer": "", "claims": [], "evidence": [], "calculations": [],
                         "sources": [], "confidence": 0.0},
            "verification": {}, "plan": {}, "trace": [], "llm_used": False,
            "latency_ms": (perf_counter() - t0) * 1000}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=15)
    ap.add_argument("--sample-seed", type=int, default=13)
    ap.add_argument("--llm", action="store_true", help="required for A/B/C/D to do anything real")
    ap.add_argument("--provider", choices=["groq", "anthropic"], default="groq",
                    help="groq: one shared free-tier RateBudget across all baselines (old "
                         "behaviour). anthropic: a paid key, split into an equal dollar "
                         "sub-budget per baseline so none is starved by run order.")
    ap.add_argument("--model", default=None, help="override the provider's default model")
    ap.add_argument("--total-cost-usd", type=float, default=3.0,
                    help="anthropic only: total $ hard cap. Split evenly across --baselines "
                         "unless --budget-split is given.")
    ap.add_argument("--budget-split", default=None,
                    help="anthropic only: 'name:usd,name:usd,...' per-baseline caps, "
                         "overriding the even split -- e.g. weight by each baseline's "
                         "measured $/question so every baseline affords the SAME sample "
                         "size instead of D (the priciest) running out first.")
    ap.add_argument("--baselines", default=",".join(BASELINES))
    ap.add_argument("--label", default="baselines")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--v2-db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--bm25", type=Path, default=_DEFAULT_BM25)
    ap.add_argument("--vector-dir", type=Path, default=_DEFAULT_VEC)
    args = ap.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    records = load_dataset(args.dataset)
    sample = stratified_sample(records, args.sample, args.sample_seed)
    names = [n.strip() for n in args.baselines.split(",") if n.strip()]

    if args.dry_run:
        by_cat: dict[str, int] = {}
        for r in sample:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        print(f"[dry-run] sample     : {len(sample)} of {len(records)} (seed {args.sample_seed})")
        print(f"[dry-run] by category: {by_cat}")
        print(f"[dry-run] baselines  : {names}")
        return 0

    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    from evaluation.evaluators import DEFAULT_EVALUATORS
    from finqa_v2.engine import FinancialEngine
    from finqa_v2.retrieval.evaluate import build_retriever
    from finqa_v2.sqlite import SqliteRepositories

    repos = SqliteRepositories(args.v2_db)
    try:
        engine = FinancialEngine(repos)
        retriever = build_retriever(repos, bm25_path=args.bm25, vector_dir=args.vector_dir)
        if "vector" not in retriever.modes:
            print("WARNING: no vector index wired -- Baseline B will retrieve nothing "
                 f"(modes={retriever.modes})")

        cap_for = budget_split(names, args.total_cost_usd, args.budget_split)

        def _make_provider(name: str):
            if not args.llm:
                return None
            if args.provider == "anthropic":
                from finqa_v2.llm import CostBudget, anthropic_provider_from_env

                model = args.model or "claude-sonnet-5"
                return anthropic_provider_from_env(model=model,
                                                   budget=CostBudget(max_cost_usd=cap_for[name]))
            from finqa_v2.llm import RateBudget, provider_from_env

            model = args.model or "openai/gpt-oss-120b"
            return provider_from_env(model=model, budget=RateBudget.from_env())

        if args.provider == "anthropic":
            print(f"cost cap: ${args.total_cost_usd:.2f} total -> {cap_for}")

        results: dict[str, list[dict]] = {}
        usage_by_baseline: dict[str, dict] = {}
        for name in names:
            provider = _make_provider(name)
            print(f"\n=== baseline {name} ===")
            if provider is not None and getattr(provider, "name", "") == "null":
                print("WARNING: no LLM provider configured -- this baseline will be a no-op")
            results[name] = run_baseline(name, sample, repos=repos, engine=engine,
                                         retriever=retriever, provider=provider,
                                         evaluators=DEFAULT_EVALUATORS, use_llm=args.llm)
            if provider is not None:
                usage_by_baseline[name] = dict(provider.usage)
                print(f"  usage: {provider.usage}")

        comparison = {}
        for name, rows in results.items():
            comparison[name] = {
                "n": len(rows), "errors": sum(1 for r in rows if r["error"]),
                "numerical": _rate(rows, "numerical"),
                "correctness": _rate(rows, "correctness"),
                "groundedness": _rate(rows, "groundedness"),
                "citation": _rate(rows, "citation"),
                "abstention": _rate(rows, "abstention"),
                "llm_usage": usage_by_baseline.get(name),
            }

        report = {
            "label": args.label, "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_commit(), "dataset": str(args.dataset),
            "config": {"sample": len(sample), "sample_seed": args.sample_seed, "llm": args.llm,
                      "provider": args.provider if args.llm else None,
                      "total_cost_usd_cap": args.total_cost_usd if args.provider == "anthropic" else None,
                      "baselines": names},
            "comparison": comparison,
            "results": results,
        }
        if usage_by_baseline:
            report["llm_usage_by_baseline"] = usage_by_baseline
            spent = [u.get("spent_usd") for u in usage_by_baseline.values() if "spent_usd" in u]
            if spent:
                report["llm_usage_total_spent_usd"] = round(sum(spent), 4)
    finally:
        repos.close()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (REPORTS_DIR / f"{args.label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n" + "=" * 78)
    print(f"  wrote {out}")
    print(f"  {'baseline':<14}{'n':>4}{'numerical':>11}{'correctness':>13}{'groundedness':>14}"
          f"{'citation':>10}{'abstention':>12}")
    for name, c in comparison.items():
        print(f"  {name:<14}{c['n']:>4}{str(c['numerical']['accuracy']):>11}"
              f"{str(c['correctness']['accuracy']):>13}{str(c['groundedness']['accuracy']):>14}"
              f"{str(c['citation']['accuracy']):>10}{str(c['abstention']['accuracy']):>12}")
    if "llm_usage_total_spent_usd" in report:
        print(f"  total spend: ${report['llm_usage_total_spent_usd']:.4f} "
             f"(cap ${report['config']['total_cost_usd_cap']:.2f})")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
