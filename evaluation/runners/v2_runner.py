"""Run a JSONL question set against the Fin_QA v2 reasoning pipeline and write a scored report.

    python -m evaluation.runners.v2_runner --dataset evaluation/datasets/finqa_v2_eval.jsonl \
        --label det-v2 [--llm] [--limit N] [--filter-category numerical] [--no-retriever] [--dry-run]

Deterministic by default (no LLM, spends no tokens). --llm shares one RateBudget across the run.
See docs/file-guide.md.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "evaluation" / "reports"
_DATA = ROOT / "database" / "data"
_DEFAULT_DB = _DATA / "finqa_v2.db"
_DEFAULT_BM25 = _DATA / "finqa_v2_bm25.pkl"
_DEFAULT_VEC = _DATA / "finqa_v2_vec"
_RETRIEVAL_CASES = ROOT / "finqa_v2" / "retrieval" / "eval_cases.jsonl"


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                       text=True).strip()
    except Exception:
        return "unknown"


def load_dataset(path: Path) -> list[dict]:
    out: list[dict] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path}:{lineno}: bad JSON — {e}") from e
    return out


def _rate(rows: list[dict], name: str) -> dict:
    """pass / (pass+fail) for one evaluator verdict across records."""
    vs = [r["scores"].get(name, {}).get("verdict") for r in rows]
    p = sum(1 for v in vs if v == "pass")
    f = sum(1 for v in vs if v == "fail")
    w = sum(1 for v in vs if v == "warn")
    return {"passed": p, "failed": f, "warned": w, "checked": p + f + w,
            "accuracy": round(p / (p + f), 4) if (p + f) else None}


def _mean_metric(rows: list[dict], ev: str, metric: str) -> float | None:
    vals = [r["scores"].get(ev, {}).get("metrics", {}).get(metric) for r in rows]
    vals = [v for v in vals if isinstance(v, (int, float))]
    return round(statistics.fmean(vals), 4) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--label", default="v2")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sample", type=int, default=None,
                    help="stratified sample of ~N records (proportional per category)")
    ap.add_argument("--sample-seed", type=int, default=13)
    ap.add_argument("--filter-category", default=None)
    ap.add_argument("--llm", action="store_true", help="use the LLM synthesizer (spends tokens)")
    ap.add_argument("--no-retriever", action="store_true", help="skip wiring BM25/vector into the pipeline")
    ap.add_argument("--skip-retrieval-eval", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="explicit report path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--v2-db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--bm25", type=Path, default=_DEFAULT_BM25)
    ap.add_argument("--vector-dir", type=Path, default=_DEFAULT_VEC)
    args = ap.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    records = load_dataset(args.dataset)
    if args.filter_category:
        records = [r for r in records if r.get("category") == args.filter_category]
    if args.sample and args.sample < len(records):
        import random as _rnd

        rng = _rnd.Random(args.sample_seed)
        by_cat: dict[str, list] = {}
        for r in records:
            by_cat.setdefault(r.get("category", "?"), []).append(r)
        frac = args.sample / len(records)
        picked: list = []
        for cat, rows in by_cat.items():
            k = max(1, round(len(rows) * frac))
            picked.extend(rng.sample(rows, min(k, len(rows))))
        rng.shuffle(picked)
        records = picked
    if args.limit:
        records = records[: args.limit]

    if args.dry_run:
        by_cat: dict[str, int] = {}
        for r in records:
            by_cat[r.get("category", "?")] = by_cat.get(r.get("category", "?"), 0) + 1
        print(f"[dry-run] dataset        : {args.dataset}")
        print(f"[dry-run] records        : {len(records)}")
        print(f"[dry-run] by category    : {by_cat}")
        print(f"[dry-run] numeric refs   : {sum(1 for r in records if r.get('reference_value') is not None)}")
        print(f"[dry-run] should_abstain : {sum(1 for r in records if r.get('should_abstain'))}")
        print(f"[dry-run] llm            : {args.llm}   retriever: {not args.no_retriever}")
        print(f"[dry-run] would write    : {args.out or (REPORTS_DIR / (args.label + '_<ts>.json'))}")
        return 0

    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db} — build it with `python -m finqa_v2.dataset.build`")

    from evaluation.evaluators import (
        OperationsEvaluator,
        RetrievalEvaluator,
        score_record,
    )
    from finqa_v2.engine import FinancialEngine
    from finqa_v2.planner.models import Intent
    from finqa_v2.reasoning import ReasoningOrchestrator
    from finqa_v2.retrieval.evaluate import build_retriever
    from finqa_v2.sqlite import SqliteRepositories

    repos = SqliteRepositories(args.v2_db)
    provider = None
    model_id = None
    try:
        engine = FinancialEngine(repos)
        retriever = None
        if not args.no_retriever and args.bm25.exists():
            retriever = build_retriever(repos, bm25_path=args.bm25, vector_dir=args.vector_dir)
        if args.llm:
            from finqa_v2.llm import RateBudget, provider_from_env

            provider = provider_from_env(budget=RateBudget.from_env())
            model_id = getattr(provider, "model", None)
        orch = ReasoningOrchestrator(repos, provider=provider, retriever=retriever, engine=engine)

        rows: list[dict] = []
        for i, rec in enumerate(records, 1):
            q = rec["question"]
            print(f"[{i}/{len(records)}] {rec['id']}: {q}")
            before = dict(provider.usage) if provider is not None else {}
            error = None
            try:
                rr = orch.answer(q, use_llm=args.llm)
                result = rr.to_dict()
            except Exception as e:  # capture, keep going
                error = repr(e)
                result = {"response": {"answer": "", "claims": [], "evidence": [],
                                       "calculations": [], "sources": [], "confidence": 0.0},
                          "plan": {}, "trace": [], "latency_ms": 0.0}
            after = dict(provider.usage) if provider is not None else {}
            llm_delta = {k: after.get(k, 0) - before.get(k, 0)
                         for k in ("prompt_tokens", "completion_tokens", "total_tokens")}

            plan = result.get("plan") or {}
            exp_intent = rec.get("expected_intent")
            intent_verdict = ("skip" if not exp_intent
                              else "pass" if plan.get("intent") == exp_intent else "fail")
            rows.append({
                "id": rec["id"], "category": rec.get("category"), "question": q,
                "error": error,
                "answer": result["response"].get("answer", ""),
                "confidence": result["response"].get("confidence"),
                "plan_intent": plan.get("intent"),
                "expected_intent": exp_intent,
                "intent_verdict": intent_verdict,
                "llm_used": result.get("llm_used", False),
                "latency_ms": result.get("latency_ms", 0.0),
                "trace": result.get("trace", []),
                "verification_status": (result.get("verification") or {}).get("status"),
                "n_claims": len(result["response"].get("claims", [])),
                "n_sources": len(result["response"].get("sources", [])),
                "llm": llm_delta,
                "scores": score_record(rec, result),
            })

        ops = OperationsEvaluator(model=model_id).run(rows)
        retrieval_block = {"skipped": "disabled"}
        if not args.skip_retrieval_eval and not args.no_retriever and args.bm25.exists():
            modes = ("lexical", "vector", "hybrid") if args.vector_dir.exists() else ("lexical",)
            retrieval_block = RetrievalEvaluator(
                v2_db=args.v2_db, bm25=args.bm25, vector_dir=args.vector_dir,
                cases_path=_RETRIEVAL_CASES, modes=modes, filter_company=True,
            ).run(repos)

        intent_checked = [r for r in rows if r["intent_verdict"] in ("pass", "fail")]
        aggregates = {
            "n_questions": len(rows),
            "errors": sum(1 for r in rows if r["error"]),
            "intent_match": {
                "checked": len(intent_checked),
                "passed": sum(1 for r in intent_checked if r["intent_verdict"] == "pass"),
            },
            "numerical": _rate(rows, "numerical"),
            "correctness": _rate(rows, "correctness"),
            "groundedness": {
                "verdict": _rate(rows, "groundedness"),
                "mean_grounded_rate": _mean_metric(rows, "groundedness", "grounded_rate"),
            },
            "citation": {
                "verdict": _rate(rows, "citation"),
                "mean_precision": _mean_metric(rows, "citation", "precision"),
                "mean_recall": _mean_metric(rows, "citation", "recall"),
                "mean_f1": _mean_metric(rows, "citation", "f1"),
            },
            "abstention": _rate(rows, "abstention"),
            "unsupported_claims": {
                "verdict": _rate(rows, "unsupported_claims"),
                "mean_rate": _mean_metric(rows, "unsupported_claims", "unsupported_rate"),
            },
            "operations": ops,
        }

        report = {
            "label": args.label,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_commit(),
            "python": sys.version.split()[0],
            "dataset": str(args.dataset),
            "config": {
                "llm": args.llm, "model": model_id, "retriever": not args.no_retriever,
                "v2_db": str(args.v2_db),
            },
            "aggregates": aggregates,
            "retrieval": retrieval_block,
            "results": rows,
        }
        if provider is not None:
            report["llm_usage_total"] = dict(provider.usage)
    finally:
        repos.close()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or (REPORTS_DIR / f"{args.label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    a = report["aggregates"]
    print("\n" + "=" * 64)
    print(f"  wrote {out_path}")
    print(f"  questions        : {a['n_questions']}  (errors: {a['errors']})")
    print(f"  intent match     : {a['intent_match']['passed']}/{a['intent_match']['checked']}")
    print(f"  numerical acc    : {a['numerical']['accuracy']}  ({a['numerical']['passed']}/{a['numerical']['checked']})")
    print(f"  correctness acc  : {a['correctness']['accuracy']}  ({a['correctness']['passed']}/{a['correctness']['checked']})")
    print(f"  groundedness     : mean {a['groundedness']['mean_grounded_rate']}  pass {a['groundedness']['verdict']['passed']}/{a['groundedness']['verdict']['checked']}")
    print(f"  citation P/R/F1  : {a['citation']['mean_precision']} / {a['citation']['mean_recall']} / {a['citation']['mean_f1']}")
    print(f"  abstention acc   : {a['abstention']['accuracy']}  ({a['abstention']['passed']}/{a['abstention']['checked']})")
    print(f"  unsupported rate : {a['unsupported_claims']['mean_rate']}")
    print(f"  latency p50/p95  : {a['operations']['latency_ms']['p50']} / {a['operations']['latency_ms']['p95']} ms")
    print(f"  llm tokens/q     : {a['operations']['llm']['tokens_per_question']}  cost/q ${a['operations']['llm']['est_cost_usd_per_question']}")
    if isinstance(report["retrieval"], dict) and "lexical" in report["retrieval"]:
        lx = report["retrieval"]["lexical"]
        print(f"  retrieval(lex)   : R@5 {lx['recall@5']}  MRR {lx['mrr']}  nDCG@10 {lx['ndcg@10']}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
