"""Fill `reference_value` / `reference_unit` on numeric rows of a v2 eval set from the
deterministic Financial Engine (the §11 source of numerical truth). See docs/file-guide.md.

    python -m evaluation.datasets.build_v2_gold [--dataset PATH] [--v2-db PATH] [--check]

Each numeric row carries a `gold_spec`: {"tool": get_metric|get_ratio|get_growth|get_valuation,
"name": <metric/ratio/valuation name>, "period": "FY2026", "kind": "yoy"}. `--check` verifies
the pinned values still match the engine (exit 1 on drift) without rewriting.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_DEFAULT_DS = ROOT / "evaluation" / "datasets" / "finqa_v2_eval.jsonl"
_DEFAULT_DB = ROOT / "database" / "data" / "finqa_v2.db"


def _engine_value(engine, spec: dict):
    tool = spec["tool"]
    name = spec.get("name")
    period = spec.get("period", "latest")
    tk = spec["ticker"]
    if tool == "get_metric":
        r = engine.get_metric(tk, name, period=period)
    elif tool == "get_ratio":
        r = engine.get_ratio(tk, name, period=period)
    elif tool == "get_valuation":
        r = engine.get_valuation(tk, name, period=period)
    elif tool == "get_growth":
        r = engine.get_growth(tk, name, kind=spec.get("kind", "yoy"))
    else:
        raise SystemExit(f"unknown gold_spec.tool: {tool}")
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=_DEFAULT_DS)
    ap.add_argument("--v2-db", type=Path, default=_DEFAULT_DB)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not args.dataset.exists():
        raise SystemExit(f"dataset not found: {args.dataset}")
    if not args.v2_db.exists():
        raise SystemExit(f"db not found: {args.v2_db}")

    from finqa_v2.engine import FinancialEngine
    from finqa_v2.sqlite import SqliteRepositories

    repos = SqliteRepositories(args.v2_db)
    rows: list[dict] = []
    filled = drift = missing = 0
    try:
        engine = FinancialEngine(repos)
        for line in args.dataset.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            spec = rec.get("gold_spec")
            if spec and rec.get("answer_type") == "numeric":
                spec.setdefault("ticker", (rec.get("companies") or [None])[0])
                res = _engine_value(engine, spec)
                if not res.ok or res.value is None:
                    missing += 1
                    print(f"  ! {rec['id']}: engine returned no value ({spec})")
                else:
                    val = round(float(res.value), 6)
                    if args.check:
                        old = rec.get("reference_value")
                        if old is None or abs(old - val) > max(abs(val) * 1e-4, 1e-6):
                            drift += 1
                            print(f"  ~ {rec['id']}: pinned {old} != engine {val}")
                    else:
                        rec["reference_value"] = val
                        rec["reference_unit"] = res.unit
                        filled += 1
            rows.append(rec)
    finally:
        repos.close()

    if args.check:
        print(f"checked: {len(rows)} rows, {drift} drifted, {missing} unresolved")
        return 1 if (drift or missing) else 0

    args.dataset.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"wrote {args.dataset}: {filled} numeric gold values filled, {missing} unresolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
