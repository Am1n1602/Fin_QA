"""Compare a candidate report against a pinned baseline; fail on regression. See docs/file-guide.md.

    python -m evaluation.regression.compare BASELINE.json CANDIDATE.json      # exit 1 on regression
    python -m evaluation.regression.compare --update BASELINE.json CANDIDATE.json   # pin candidate
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

# (metric key, "up"=higher-better / "down"=lower-better, abs slack, rel slack fraction)
TRACKED: list[tuple[str, str, float, float]] = [
    ("intent_match_rate", "up", 0.02, 0.0),
    ("numerical.accuracy", "up", 0.02, 0.0),
    ("correctness.accuracy", "up", 0.02, 0.0),
    ("groundedness.mean_grounded_rate", "up", 0.02, 0.0),
    ("citation.mean_f1", "up", 0.05, 0.0),
    ("abstention.accuracy", "up", 0.02, 0.0),
    ("unsupported_claims.mean_rate", "down", 0.02, 0.0),
    ("operations.latency_ms.p50", "down", 1.0, 0.25),
    ("operations.latency_ms.p95", "down", 1.0, 0.30),
    ("operations.llm.tokens_per_question", "down", 5.0, 0.15),
    ("retrieval.lexical.recall@5", "up", 0.03, 0.0),
    ("retrieval.lexical.mrr", "up", 0.03, 0.0),
    ("retrieval.lexical.ndcg@10", "up", 0.03, 0.0),
]


def _dig(d: Any, path: str) -> Any:
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def extract_metrics(report: dict) -> dict[str, float]:
    agg = report.get("aggregates", {})
    im = agg.get("intent_match", {})
    out: dict[str, float] = {}
    if im.get("checked"):
        out["intent_match_rate"] = round(im["passed"] / im["checked"], 4)
    for key in ("numerical.accuracy", "correctness.accuracy",
                "groundedness.mean_grounded_rate", "citation.mean_f1",
                "abstention.accuracy", "unsupported_claims.mean_rate",
                "operations.latency_ms.p50", "operations.latency_ms.p95",
                "operations.llm.tokens_per_question"):
        v = _dig(agg, key)
        if isinstance(v, (int, float)):
            out[key] = v
    lx = _dig(report, "retrieval.lexical") or {}
    for k in ("recall@5", "mrr", "ndcg@10"):
        if isinstance(lx.get(k), (int, float)):
            out[f"retrieval.lexical.{k}"] = lx[k]
    return out


def compare(baseline: dict, candidate: dict) -> dict:
    b, c = extract_metrics(baseline), extract_metrics(candidate)
    regressions, improvements, unchanged, missing = [], [], [], []
    for key, direction, abs_slack, rel_slack in TRACKED:
        if key not in b or key not in c:
            missing.append(key)
            continue
        bv, cv = b[key], c[key]
        delta = cv - bv
        slack = max(abs_slack, abs(bv) * rel_slack)
        worse = (delta < -slack) if direction == "up" else (delta > slack)
        better = (delta > slack) if direction == "up" else (delta < -slack)
        row = {"metric": key, "baseline": bv, "candidate": cv,
               "delta": round(delta, 4), "slack": round(slack, 4), "direction": direction}
        (regressions if worse else improvements if better else unchanged).append(row)
    return {
        "ok": not regressions,
        "regressions": regressions,
        "improvements": improvements,
        "unchanged": unchanged,
        "not_in_both": missing,
    }


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("baseline", type=Path)
    ap.add_argument("candidate", type=Path)
    ap.add_argument("--update", action="store_true",
                    help="copy candidate over baseline (pin a new baseline) and exit 0")
    ap.add_argument("--json", type=Path, default=None, help="write the diff as JSON")
    args = ap.parse_args()

    if not args.candidate.exists():
        raise SystemExit(f"candidate not found: {args.candidate}")
    if args.update:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.candidate, args.baseline)
        print(f"pinned {args.candidate} -> {args.baseline}")
        return 0
    if not args.baseline.exists():
        raise SystemExit(f"baseline not found: {args.baseline} (pin one with --update)")

    diff = compare(_load(args.baseline), _load(args.candidate))
    if args.json:
        args.json.write_text(json.dumps(diff, indent=2), encoding="utf-8")

    def _fmt(r):
        return f"    {r['metric']:38s} {r['baseline']!s:>10} -> {r['candidate']!s:<10} (Δ {r['delta']:+}, slack {r['slack']})"

    print(f"baseline : {args.baseline}")
    print(f"candidate: {args.candidate}")
    print(f"\nregressions ({len(diff['regressions'])}):")
    for r in diff["regressions"]:
        print(_fmt(r))
    print(f"improvements ({len(diff['improvements'])}):")
    for r in diff["improvements"]:
        print(_fmt(r))
    print(f"unchanged: {len(diff['unchanged'])}   not-in-both: {diff['not_in_both']}")
    print(f"\n{'OK — no regression' if diff['ok'] else 'REGRESSION'}")
    return 0 if diff["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
