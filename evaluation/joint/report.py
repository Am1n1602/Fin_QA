"""Retrieval + Answer Joint Evaluation (§24): high retrieval Recall@K does not
automatically mean a correct answer -- assemble already-measured retrieval quality
(`evaluation/run_retrieval_benchmark.py`'s own `--out` JSON) and answer quality
(`evaluation/runners/v2_runner.py`'s own report JSON) into one comparable
experiment-table row per configuration, instead of leaving them as two disconnected
reports nobody reads side by side.

Never re-runs either eval itself -- both stay each harness's own job; this only reads
what's already been measured and saved, so the numbers here are exactly reproducible from
the cited files.

    python -m evaluation.joint.report \\
        --row "v2.0 baseline|evaluation/results/retrieval_v21_baseline.json|evaluation/reports/det-v2_20260911_023246.json" \\
        --row "current production|evaluation/results/retrieval_v21_mmr_production.json|evaluation/reports/v2_20260914_213305.json" \\
        --out evaluation/results/joint_v21_experiment_table.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

_COLUMNS = ("configuration", "recall@5", "mrr", "ndcg@5", "answer_accuracy", "groundedness",
           "abstention_accuracy", "citation_f1", "retrieval_p50_ms", "answer_p95_ms")


def build_row(label: str, retrieval_report: Path, answer_report: Path) -> dict[str, Any]:
    """`retrieval_report`: a JSON file written by `run_retrieval_benchmark.py --out ...`
    (must include a `"hybrid"` mode). `answer_report`: a JSON file written by
    `evaluation/runners/v2_runner.py` (has an `"aggregates"` block)."""
    retrieval = json.loads(Path(retrieval_report).read_text(encoding="utf-8"))
    answer = json.loads(Path(answer_report).read_text(encoding="utf-8"))

    hybrid = retrieval["results"]["hybrid"]
    agg = answer["aggregates"]
    return {
        "configuration": label,
        "recall@5": hybrid["recall@5"],
        "mrr": hybrid["mrr"],
        "ndcg@5": hybrid.get("ndcg@5"),
        "retrieval_p50_ms": hybrid["p50_ms"],
        "answer_accuracy": agg["correctness"]["accuracy"],
        "groundedness": agg["groundedness"]["verdict"]["accuracy"],
        "citation_f1": agg["citation"]["mean_f1"],
        "abstention_accuracy": agg["abstention"]["accuracy"],
        "answer_p50_ms": agg["operations"]["latency_ms"]["p50"],
        "answer_p95_ms": agg["operations"]["latency_ms"]["p95"],
        "_sources": {"retrieval_report": str(retrieval_report), "answer_report": str(answer_report)},
    }


def render_table(rows: list[dict[str, Any]]) -> str:
    header = " | ".join(_COLUMNS)
    lines = [header, " | ".join("---" for _ in _COLUMNS)]
    for r in rows:
        lines.append(" | ".join(str(r.get(c, "")) for c in _COLUMNS))
    return "\n".join(lines)


def _parse_row_spec(spec: str) -> tuple[str, Path, Path]:
    label, retrieval_path, answer_path = spec.split("|", 2)
    return label, Path(retrieval_path), Path(answer_path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--row", action="append", default=[],
                    help="label|retrieval_report.json|answer_report.json (repeatable)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    if not args.row:
        raise SystemExit("at least one --row is required, e.g. "
                         "--row 'label|retrieval_report.json|answer_report.json'")

    rows = [build_row(*_parse_row_spec(spec)) for spec in args.row]

    print(render_table(rows))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
