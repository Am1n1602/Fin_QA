"""Source reconciliation audit (roadmap Step 3 / §12): detects when the SAME
financial fact -- (company, basis, period_start, period_end, metric) -- is
produced by more than one source filing, and whether their values agree.

Per §0.3/§4, XBRL is the only source for financial_facts, so "reconciliation"
here is XBRL-internal: the same period can legitimately appear in more than one
filing (e.g. a quarter's own filing, plus that same quarter surfacing again as a
"corresponding period" comparator in a later filing). `financial_facts.add_many()`
(finqa_v2/sqlite/repo.py) is a plain upsert keyed on this exact grain -- whichever
canonical file is processed last silently wins, with no precedence rule and no
history of what the loser said. This audit operates on the canonical JSON files
directly (data_extraction/data/extracted/), catching a conflict independent of,
and before, that collapse -- the database only ever shows the winner.

    python -m finqa_v2.dataset.reconcile [--extracted-dir PATH] [--company TICKER]
        [--json OUT.json] [--check]        # --check exits 1 if any conflict exists
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from finqa_v2.normalize.pipeline import _parse_filename

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXTRACTED_DIR = _REPO_ROOT / "data_extraction" / "data" / "extracted"

_META_KEYS = frozenset(
    {"context_id", "period_start", "period_end", "instant",
     "_missing_fields", "_validation", "_needs_review"}
)


def find_conflicts(extracted_dir: Path = _EXTRACTED_DIR, *, company: str | None = None) -> list[dict]:
    """-> one entry per (company, basis, period, metric) that got a DIFFERENT
    value from more than one canonical file. An empty list means every fact-grain
    in scope has at most one contributing source -- the common, expected case."""
    # grain -> {metric: {source_filename: value}}
    grains: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))

    for path in sorted(extracted_dir.glob("*_canonical.json")):
        parsed = _parse_filename(path.name)
        if parsed is None:
            continue
        symbol, basis, _period_label = parsed
        if company and symbol != company:
            continue
        records = json.loads(path.read_text(encoding="utf-8"))
        for record in records:
            grain = (symbol, basis, record.get("period_start"), record.get("period_end"))
            for key, value in record.items():
                if key in _META_KEYS or isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                grains[grain][key][path.name] = value

    conflicts = []
    for (symbol, basis, ps, pe), by_metric in grains.items():
        for metric, by_file in by_metric.items():
            distinct = {round(v, 2) for v in by_file.values()}
            if len(distinct) > 1:
                conflicts.append({
                    "company": symbol, "basis": basis,
                    "period_start": ps, "period_end": pe, "metric": metric,
                    "values_by_source": by_file,
                })
    conflicts.sort(key=lambda c: (c["company"], c["metric"], c["period_end"] or ""))
    return conflicts


def _print(conflicts: list[dict]) -> None:
    if not conflicts:
        print("source reconciliation: 0 conflicts -- every fact-grain in scope has "
              "at most one contributing source filing")
        return
    print(f"source reconciliation: {len(conflicts)} conflict(s) found\n")
    for c in conflicts:
        print(f"  {c['company']} {c['basis']} {c['metric']} "
              f"[{c['period_start']} -> {c['period_end']}]")
        for src, val in c["values_by_source"].items():
            print(f"      {val!r:>20}  <- {src}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--extracted-dir", type=Path, default=_EXTRACTED_DIR)
    ap.add_argument("--company")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if not args.extracted_dir.exists():
        raise SystemExit(f"extracted dir not found: {args.extracted_dir}")

    conflicts = find_conflicts(args.extracted_dir, company=args.company)
    _print(conflicts)
    if args.json:
        args.json.write_text(json.dumps(conflicts, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 1 if (args.check and conflicts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
