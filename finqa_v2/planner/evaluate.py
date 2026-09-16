"""Query-planner evaluation (§44). Compares the rules planner against the LLM planner
on intent accuracy, company extraction, tool selection, plan validity and latency, so
the LLM planner is only kept if it measurably beats rules.

    python -m finqa_v2.planner.evaluate [--llm] [--cases PATH] [--v2-db PATH]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from finqa_v2.planner.models import Intent
from finqa_v2.planner.planner import QueryPlanner
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_CASES = Path(__file__).with_name("planner_eval_cases.jsonl")


def load_cases(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _prf(pred: set, gold: set) -> tuple[float, float, float]:
    if not gold and not pred:
        return 1.0, 1.0, 1.0
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def evaluate(planner: QueryPlanner, cases: list[dict], *, use_llm: bool) -> dict:
    intent_hits = 0
    co_tp = co_pred = co_gold = 0
    tool_f1s: list[float] = []
    must_hits = 0
    valid = 0
    lat: list[float] = []
    rows = []
    for c in cases:
        t0 = time.perf_counter()
        plan = planner.plan(c["question"], use_llm=use_llm)
        lat.append((time.perf_counter() - t0) * 1000)

        intent_ok = plan.intent.value == c["intent"]
        intent_hits += intent_ok

        gold_co = set(c.get("companies", []))
        pred_co = set(plan.companies)
        co_tp += len(pred_co & gold_co)
        co_pred += len(pred_co)
        co_gold += len(gold_co)

        _, _, f = _prf(set(plan.tools), set(c.get("ideal_tools", [])))
        tool_f1s.append(f)
        must = set(c.get("must_tools", []))
        must_hits += must.issubset(set(plan.tools))
        valid += (plan.intent is Intent.UNKNOWN) or bool(plan.tools)

        rows.append({"id": c["id"], "intent": plan.intent.value, "intent_ok": intent_ok,
                     "companies": plan.companies, "tools": plan.tools, "planner": plan.planner})

    n = len(cases)
    co_p = co_tp / co_pred if co_pred else 0.0
    co_r = co_tp / co_gold if co_gold else 1.0
    return {
        "n": n,
        "intent_accuracy": round(intent_hits / n, 3),
        "company_precision": round(co_p, 3),
        "company_recall": round(co_r, 3),
        "company_f1": round(2 * co_p * co_r / (co_p + co_r), 3) if (co_p + co_r) else 0.0,
        "tool_f1_mean": round(statistics.fmean(tool_f1s), 3),
        "must_tools_hit_rate": round(must_hits / n, 3),
        "plan_valid_rate": round(valid / n, 3),
        "p50_ms": round(statistics.median(lat), 1),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=Path, default=_CASES)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--llm", action="store_true", help="also run the LLM planner (spends tokens)")
    args = ap.parse_args()
    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    cases = load_cases(args.cases)
    repos = SqliteRepositories(args.v2_db)
    try:
        provider = None
        if args.llm:
            from finqa_v2.llm import RateBudget, provider_from_env

            # one shared budget so the whole eval run stays under the free-tier caps
            budget = RateBudget.from_env()
            provider = provider_from_env(budget=budget)
        planner = QueryPlanner(repos, provider=provider)
        rules = evaluate(planner, cases, use_llm=False)
        print(f"cases={rules['n']}")
        _print("rules", rules)
        if args.llm and provider is not None and provider.name != "null":
            llm = evaluate(planner, cases, use_llm=True)
            _print("llm", llm)
            print(f"  llm usage: {provider.usage}")
    finally:
        repos.close()
    return 0


def _print(label: str, r: dict) -> None:
    print(f"  {label:6s} intent={r['intent_accuracy']} company_f1={r['company_f1']} "
          f"tool_f1={r['tool_f1_mean']} must_tools={r['must_tools_hit_rate']} "
          f"valid={r['plan_valid_rate']} p50={r['p50_ms']}ms")


if __name__ == "__main__":
    raise SystemExit(main())
