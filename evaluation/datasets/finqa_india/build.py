"""Build evaluation/datasets/finqa_india.jsonl — the §38 internal benchmark.

    python -m evaluation.datasets.finqa_india.build [--target 850] [--seed 20]
        [--v2-db PATH] [--out PATH] [--dry-run]

Templated candidates (engine-probed, numeric gold embedded) + the hand-authored
`curated.jsonl`, deduped and balanced toward the §38 quotas. See docs/file-guide.md.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_HERE = Path(__file__).parent
_CURATED = _HERE / "curated.jsonl"
_DEFAULT_OUT = ROOT / "evaluation" / "datasets" / "finqa_india.jsonl"
_DEFAULT_DB = ROOT / "database" / "data" / "finqa_v2.db"


def _load_curated() -> list[dict]:
    if not _CURATED.exists():
        return []
    return [json.loads(l) for l in _CURATED.read_text(encoding="utf-8").splitlines() if l.strip()]


def _norm(q: str) -> str:
    return " ".join(q.lower().split())


def _balance(cands: list[dict], curated: list[dict], quota: int, cap: int, rng: random.Random) -> list[dict]:
    """curated first, then generated up to `quota`, ≤ `cap` per company."""
    chosen: list[dict] = []
    seen: set[str] = set()
    per_co: Counter = Counter()

    def _take(r: dict) -> bool:
        k = _norm(r["question"])
        if k in seen:
            return False
        co = (r.get("companies") or ["_"])[0]
        if per_co[co] >= cap:
            return False
        seen.add(k)
        per_co[co] += 1
        chosen.append(r)
        return True

    for r in curated:
        if len(chosen) >= quota:
            break
        _take(r)
    pool = cands[:]
    rng.shuffle(pool)
    for r in pool:
        if len(chosen) >= quota:
            break
        _take(r)
    # second pass ignoring the per-company cap if still short
    if len(chosen) < quota:
        for r in pool:
            if len(chosen) >= quota:
                break
            k = _norm(r["question"])
            if k not in seen:
                seen.add(k)
                chosen.append(r)
    return chosen


def build(repos, engine, *, target: int, seed: int) -> list[dict]:
    from evaluation.datasets.finqa_india.audit import scaled_quotas
    from evaluation.datasets.finqa_india.generate import generate

    rng = random.Random(seed)
    quotas = scaled_quotas(target)
    gen = generate(repos, engine, seed=seed)
    curated_by_cat: dict[str, list[dict]] = {}
    for r in _load_curated():
        curated_by_cat.setdefault(r["category"], []).append(r)

    out: list[dict] = []
    for cat, quota in quotas.items():
        cap = max(3, math.ceil(quota / 12))
        rows = _balance(gen.get(cat, []), curated_by_cat.get(cat, []), quota, cap, rng)
        for r in rows:
            r["category"] = cat
        out.extend(rows)

    _SCHEMA = {
        "companies": [], "period": None, "answer_type": "text", "expected_intent": None,
        "should_abstain": False, "gold_spec": None, "reference_value": None,
        "reference_unit": None, "reference_answer": None, "reference_sources": [],
        "tolerance_pct": None, "must_contain": [], "notes": "",
    }
    for i, r in enumerate(out):
        for k, v in _SCHEMA.items():
            r.setdefault(k, list(v) if isinstance(v, list) else v)
        r["id"] = f"fqi-{r['category'][:4]}-{i:04d}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", type=int, default=850)
    ap.add_argument("--seed", type=int, default=20)
    ap.add_argument("--v2-db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    ap.add_argument("--dry-run", action="store_true", help="print the audit, do not write")
    args = ap.parse_args()
    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    from evaluation.datasets.finqa_india.audit import audit, format_audit
    from finqa_v2.engine import FinancialEngine
    from finqa_v2.sqlite import SqliteRepositories

    repos = SqliteRepositories(args.v2_db)
    try:
        engine = FinancialEngine(repos)
        records = build(repos, engine, target=args.target, seed=args.seed)
    finally:
        repos.close()

    a = audit(records, target=args.target)
    print(format_audit(a))
    if args.dry_run:
        return 0
    args.out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
                        encoding="utf-8")
    print(f"\nwrote {args.out}  ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
