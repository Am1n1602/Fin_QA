"""
baseline_runner.py -- run a JSONL question set against the v1 QA path and write a report.

It does NOT score correctness -- there are no reference answers yet. What it captures,
per question: assigned intent, the answer text, classification, source counts, LLM-synthesis
status, latency, plus two verdicts that already work now (intent-match vs expected_intent_v1,
and abstention behavior for should_abstain items).

Usage:
    python evaluation/runners/baseline_runner.py \
        --dataset evaluation/datasets/finqa_india_starter.jsonl \
        --label v1-baseline
    # optional:  --db-path path/to/financial_intelligence.db  --limit N  --company-qa

Requires a built database (default: database/data/financial_intelligence.db). Run
`finqa-pipeline` first if it does not exist.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QA_ROUTER_DIR = ROOT / "archive" / "qa_router"          # v1 moved into archive/
REPORTS_DIR = ROOT / "evaluation" / "reports"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT), text=True
        ).strip()
    except Exception:  # noqa: BLE001 -- best-effort provenance
        return "unknown"


def _load_dataset(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{lineno}: bad JSON -- {e}") from e
    return records


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 4)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, type=Path)
    ap.add_argument("--label", default="baseline", help="Report filename prefix / run label.")
    ap.add_argument("--db-path", default=None, help="Override the QA database path.")
    ap.add_argument("--limit", type=int, default=None, help="Only run the first N records.")
    ap.add_argument("--company-qa", action="store_true",
                    help="Pin company resolution to record['companies'][0] when present "
                         "(mirrors POST /companies/{symbol}/qa).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Validate + print the run plan and exit. Does not import qa_router "
                         "or load any model -- works on any machine.")
    args = ap.parse_args()

    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")

    if args.dry_run:
        records = _load_dataset(args.dataset)
        if args.limit:
            records = records[: args.limit]
        by_cat: dict[str, int] = {}
        by_intent: dict[str, int] = {}
        for r in records:
            by_cat[r.get("category")] = by_cat.get(r.get("category"), 0) + 1
            exp = r.get("expected_intent_v1") or "(unpinned)"
            by_intent[exp] = by_intent.get(exp, 0) + 1
        print(f"[dry-run] dataset            : {args.dataset}")
        print(f"[dry-run] records            : {len(records)}")
        print(f"[dry-run] by category        : {by_cat}")
        print(f"[dry-run] by expected_intent : {by_intent}")
        print(f"[dry-run] should_abstain     : {sum(1 for r in records if r.get('should_abstain'))}")
        print(f"[dry-run] company-qa mode    : {args.company_qa}")
        print("[dry-run] would call qa_router.answer_question() once per record and write a "
              f"report to {REPORTS_DIR}/{args.label}_<ts>.json")
        return 0

    sys.path.insert(0, str(QA_ROUTER_DIR))
    sys.path.insert(0, str(ROOT))

    # Cheap import first (pathlib only) so the no-database case fails fast, before the
    # heavy qa_router import chain (torch / sentence-transformers / bridges).
    try:
        from src.config import DB_PATH  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"could not import qa_router config (`from src.config import DB_PATH`): {e}\n"
            "Run from an editable install with the sibling folders present."
        ) from e

    db_path = args.db_path or str(DB_PATH)
    if not Path(db_path).exists():
        raise SystemExit(
            f"database not found: {db_path}\n"
            "Build it first with `finqa-pipeline` (or pass --db-path). Phase 0 does not "
            "require this run -- the scaffold is what Phase 0 delivers."
        )

    try:
        from src.qa import answer_question  # noqa: PLC0415
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            f"could not import qa_router (`from src.qa import answer_question`): {e}\n"
            "Run from an editable install with the sibling folders present."
        ) from e
    from evaluation.evaluators import abstention_verdict, intent_match_verdict  # noqa: PLC0415

    records = _load_dataset(args.dataset)
    if args.limit:
        records = records[: args.limit]

    results: list[dict] = []
    latencies: list[float] = []
    for i, rec in enumerate(records, 1):
        q = rec["question"]
        override = None
        if args.company_qa and rec.get("companies"):
            override = [rec["companies"][0]]
        print(f"[{i}/{len(records)}] {rec['id']}: {q}")
        start = time.time()
        error = None
        try:
            out = answer_question(q, db_path=db_path, companies_override=override)
        except Exception as e:  # noqa: BLE001 -- capture, don't abort the run
            out = {"intent": "ERROR", "answer": "", "classification": {}, "sources": [],
                   "warnings": [], "caveats": [], "data": {}}
            error = repr(e)
        elapsed = round(time.time() - start, 3)
        latencies.append(elapsed)

        data = out.get("data") or {}
        narr = data.get("narrative", {}).get("data", data)  # complex nests under narrative
        row = {
            "id": rec["id"],
            "category": rec.get("category"),
            "question": q,
            "elapsed_s": elapsed,
            "error": error,
            "intent": out.get("intent"),
            "expected_intent_v1": rec.get("expected_intent_v1"),
            "classification": out.get("classification"),
            "answer": out.get("answer"),
            "n_sources": len(out.get("sources") or []),
            "n_warnings": len(out.get("warnings") or []),
            "n_caveats": len(out.get("caveats") or []),
            "llm_synthesis_used": narr.get("llm_synthesis_used"),
            "llm_synthesis_status": narr.get("llm_synthesis_status"),
            "verdict_intent": intent_match_verdict(rec, out),
            "verdict_abstention": abstention_verdict(rec, out),
        }
        results.append(row)

    intents: dict[str, int] = {}
    for r in results:
        intents[r["intent"]] = intents.get(r["intent"], 0) + 1
    intent_checked = [r for r in results if r["verdict_intent"]["verdict"] in ("pass", "fail")]
    abst_checked = [r for r in results if r["verdict_abstention"]["verdict"] in ("pass", "fail")]

    report = {
        "label": args.label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "python": sys.version.split()[0],
        "dataset": str(args.dataset),
        "db_path": db_path,
        "n_questions": len(results),
        "config": {
            "company_qa": args.company_qa,
            "embedding_model": "all-mpnet-base-v2",
            "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        },
        "aggregates": {
            "intent_distribution": intents,
            "latency_s": {
                "mean": round(statistics.fmean(latencies), 4) if latencies else None,
                "p50": _percentile(latencies, 0.50),
                "p95": _percentile(latencies, 0.95),
                "max": max(latencies) if latencies else None,
            },
            "intent_match": {
                "checked": len(intent_checked),
                "passed": sum(1 for r in intent_checked if r["verdict_intent"]["verdict"] == "pass"),
            },
            "abstention": {
                "checked": len(abst_checked),
                "passed": sum(1 for r in abst_checked if r["verdict_abstention"]["verdict"] == "pass"),
            },
            "errors": sum(1 for r in results if r["error"]),
        },
        "results": results,
    }

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"{args.label}_{stamp}.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    agg = report["aggregates"]
    print("\n" + "=" * 60)
    print(f"  wrote {out_path}")
    print(f"  questions      : {report['n_questions']}  (errors: {agg['errors']})")
    print(f"  intent match   : {agg['intent_match']['passed']}/{agg['intent_match']['checked']}")
    print(f"  abstention ok  : {agg['abstention']['passed']}/{agg['abstention']['checked']}")
    print(f"  latency p50/p95: {agg['latency_s']['p50']}s / {agg['latency_s']['p95']}s")
    print(f"  intents        : {agg['intent_distribution']}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
