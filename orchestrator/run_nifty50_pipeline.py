"""
Usage:
    python run_nifty50_pipeline.py                  # full pipeline
    python run_nifty50_pipeline.py --only fetch      # just one stage
    python run_nifty50_pipeline.py --skip universe   # skip the universe refresh
    python run_nifty50_pipeline.py --dry-run         # print the stage plan, run nothing

"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
import subprocess

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


_CHILD_ENV = os.environ.copy()
_CHILD_ENV["PYTHONIOENCODING"] = "utf-8"
_CHILD_ENV["PYTHONUTF8"] = "1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

STAGES: list[tuple[str, str, list[str]]] = [
    ("universe", "data_extraction", ["-m", "src.universe", "--refresh"]),
    ("fetch", "data_extraction", ["-m", "src.fetch.run_pipeline"]),
    ("extract", "data_extraction", ["-m", "src.extract.run_extraction_all"]),
    ("analyze", "data_analysis", ["-m", "src.analysis.combine_and_analyze_all"]),
    ("load", "database", ["-m", "src.load_data"]),
    ("rag_ingest", "rag", ["-m", "src.pipeline.run_ingest",
                            "--meta-dir", "../data_extraction/data/meta",
                            "--db-path", "../database/data/financial_intelligence.db",
                            "--index-dir", "data/indices"]),
]


def _run_stage(name: str, cwd: Path, cmd: list[str], log_fh) -> tuple[bool, float]:
    full_cmd = [sys.executable] + cmd
    header = f"\n{'=' * 70}\n[{name}] START  {datetime.now().isoformat()}  ({' '.join(full_cmd)}, cwd={cwd})\n{'=' * 70}"
    print(header)
    log_fh.write(header + "\n")
    log_fh.flush()

    start = time.time()
    try:
        proc = subprocess.Popen(
            full_cmd, cwd=str(cwd), env=_CHILD_ENV,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as e:
        msg = f"[{name}] FAILED TO START: {e}"
        print(msg)
        log_fh.write(msg + "\n")
        return False, time.time() - start

    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        log_fh.write(line)
    log_fh.flush()
    returncode = proc.wait()

    elapsed = time.time() - start
    status = "OK" if returncode == 0 else f"FAILED (exit {returncode})"
    footer = f"[{name}] {status}  ({elapsed:.1f}s)"
    print(footer)
    log_fh.write(footer + "\n")
    log_fh.flush()
    return returncode == 0, elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=[s[0] for s in STAGES], default=None,
                     help="Run exactly one stage instead of the full pipeline.")
    ap.add_argument("--skip", action="append", choices=[s[0] for s in STAGES], default=[],
                     help="Skip a stage (repeatable). Ignored if --only is set.")
    ap.add_argument("--dry-run", action="store_true",
                     help="Print the stage plan and exit without running anything.")
    args = ap.parse_args()

    stages_to_run = STAGES
    if args.only:
        stages_to_run = [s for s in STAGES if s[0] == args.only]
    elif args.skip:
        stages_to_run = [s for s in STAGES if s[0] not in args.skip]

    if args.dry_run:
        print("[dry-run] Stage plan:")
        for name, subdir, cmd in stages_to_run:
            print(f"  {name:12s} cwd={PROJECT_ROOT / subdir}  python {' '.join(cmd)}")
        return 0

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"pipeline_{run_id}.log"
    print(f"[orchestrator] Run {run_id} starting. Full log: {log_path}")

    results: list[tuple[str, bool, float]] = []
    with open(log_path, "w", encoding="utf-8") as log_fh:
        log_fh.write(f"NIFTY 50 pipeline run {run_id}\nStages: {[s[0] for s in stages_to_run]}\n")
        for name, subdir, cmd in stages_to_run:
            cwd = PROJECT_ROOT / subdir
            if not cwd.exists():
                msg = f"[{name}] SKIPPED -- expected directory not found: {cwd}"
                print(msg)
                log_fh.write(msg + "\n")
                results.append((name, False, 0.0))
                continue
            ok, elapsed = _run_stage(name, cwd, cmd, log_fh)
            results.append((name, ok, elapsed))

    print(f"\n{'=' * 70}\n[orchestrator] Run {run_id} summary\n{'=' * 70}")
    all_ok = True
    for name, ok, elapsed in results:
        print(f"  {name:12s} {'OK' if ok else 'FAILED':8s} {elapsed:6.1f}s")
        all_ok = all_ok and ok
    print(f"\nFull log: {log_path}")

    if not all_ok:
        print("[orchestrator] One or more stages failed -- see the log above/file for details. "
              "This is often partial (e.g. one company's fetch failing doesn't stop the others "
              "within that stage) -- check the stage's own output, not just this summary, before "
              "assuming the whole run was wasted.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())