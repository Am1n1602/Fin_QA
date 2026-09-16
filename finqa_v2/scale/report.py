"""Scale report (§48 Phase 16): footprint + latency benchmark + 100/250/500 projection.

    python -m finqa_v2.scale.report [--v2-db PATH] [--no-retriever] [--repeats N]
        [--json OUT.json]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import finqa_v2.scale.benchmark as _bench
import finqa_v2.scale.measure as _measure
import finqa_v2.scale.project as _project
from finqa_v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_ROOT = Path(__file__).resolve().parents[2]
_BM25 = _ROOT / "database" / "data" / "finqa_v2_bm25.pkl"


def build_report(repos, *, with_retriever: bool = True, repeats: int = 8) -> dict:
    retriever = None
    if with_retriever and _BM25.exists():
        try:
            from finqa_v2.retrieval import BM25Index, HybridRetriever

            retriever = HybridRetriever(repos, bm25=BM25Index.load(_BM25))
        except Exception as e:
            print(f"(retriever unavailable: {e})")

    footprint = _measure.measure_footprint(repos)
    bench = _bench.benchmark_queries(repos, retriever=retriever, repeats=repeats)
    projection = _project.project(footprint, bench)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "footprint": footprint,
        "benchmark": bench,
        "projection": projection,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--no-retriever", action="store_true")
    ap.add_argument("--repeats", type=int, default=8)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    with SqliteRepositories(args.v2_db) as repos:
        rep = build_report(repos, with_retriever=not args.no_retriever, repeats=args.repeats)

    print(_measure.render(rep["footprint"]))
    print()
    print(_bench.render(rep["benchmark"]))
    print()
    print(_project.render(rep["projection"]))
    if args.json:
        args.json.write_text(json.dumps(rep, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
