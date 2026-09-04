"""
qa_router/src/bridges/analysis_worker.py

Run standalone only for debugging:
    python analysis_worker.py --project-dir /path/to/data_analysis
    (then type a request line, e.g.)
    {"id": 1, "command": "compute_financial_health", "params": {"company": "TCS", "filing_type": "consolidated"}}

Normally launched by analysis_bridge.py -- never invoked directly.
"""

from __future__ import annotations

import argparse
import json
import sys

from worker_protocol import install_protocol_stdout, run_worker_loop


def main() -> None:
    real_stdout = install_protocol_stdout()

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True,
                         help="Path to the data_analysis/ directory (the one containing its own src/ package).")
    args = parser.parse_args()

    sys.path.insert(0, args.project_dir)

    from src.analysis.combine_and_analyze import find_canonical_files
    from src.analysis.financial_health import compute_financial_health
    from src.analysis.peer_comparison import compare_peers
    from src.analysis.ranking import compute_rankings
    from src.analysis.ratios import analyze
    from src.reports.aggregator import compute_company_report

    def _load_records(company: str, filing_type: str) -> list[dict]:
        files = find_canonical_files(company, filing_type)
        records: list[dict] = []
        for f in files:
            records.extend(json.loads(f.read_text()))
        return records

    def dispatch(command: str, params: dict):
        if command == "compare_peers":
            return compare_peers(
                symbols=params["symbols"],
                metric_names=params["metric_names"],
                filing_type=params.get("filing_type", "consolidated"),
                db_path=params["db_path"],
            )
        if command == "compute_rankings":
            return compute_rankings(
                symbols=params["symbols"],
                filing_type=params.get("filing_type", "consolidated"),
                db_path=params["db_path"],
            )
        if command == "compute_financial_health":
            return compute_financial_health(
                params["company"], params.get("filing_type", "consolidated"),
            )
        if command == "compute_company_report":
            return compute_company_report(
                params["symbol"], params["peer_symbols"],
                filing_type=params.get("filing_type", "consolidated"),
                db_path=params["db_path"],
            )
        if command == "analyze_trends":
            records = _load_records(params["company"], params.get("filing_type", "consolidated"))
            return analyze(records)
        raise ValueError(f"Unknown command: {command!r}")

    run_worker_loop(real_stdout, dispatch)


if __name__ == "__main__":
    main()
