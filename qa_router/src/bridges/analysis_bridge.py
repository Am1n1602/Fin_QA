"""
Usage:
    bridge = AnalysisBridge()                 # lazy -- subprocess not started yet
    result = bridge.compare_peers(symbols=["TCS", "INFY"], metric_names=["roe_pct"])
    ...
    bridge.close()                              # or use as a context manager
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.config import DATA_ANALYSIS_DIR, DB_PATH

_WORKER_SCRIPT = Path(__file__).with_name("analysis_worker.py")


class AnalysisBridge:
    def __init__(self, db_path: str | Path = DB_PATH, data_analysis_dir: str | Path = DATA_ANALYSIS_DIR):
        self.db_path = str(db_path)
        self.data_analysis_dir = str(data_analysis_dir)
        self._proc: subprocess.Popen | None = None
        self._next_id = 1

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [sys.executable, str(_WORKER_SCRIPT), "--project-dir", self.data_analysis_dir],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
            text=True, bufsize=1,  # line-buffered
        )

    def _call(self, command: str, params: dict) -> Any:
        self._ensure_started()
        assert self._proc is not None and self._proc.stdin is not None and self._proc.stdout is not None
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, "command": command, "params": params}
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            raise RuntimeError(
                f"data_analysis worker exited unexpectedly while handling '{command}' "
                f"(exit code {self._proc.poll()}). Check its stderr output above."
            )
        response = json.loads(line)
        if response["id"] != request_id:
            raise RuntimeError(
                f"data_analysis worker response id mismatch: expected {request_id}, got {response['id']}"
            )
        if not response["ok"]:
            raise RuntimeError(f"data_analysis worker error on '{command}': {response['error']}")
        return response["result"]

    # --- public API -- one method per real data_analysis function this router calls ---

    def compare_peers(self, symbols: list[str], metric_names: list[str],
                       filing_type: str = "consolidated") -> dict:
        return self._call("compare_peers", {
            "symbols": symbols, "metric_names": metric_names,
            "filing_type": filing_type, "db_path": self.db_path,
        })

    def compute_rankings(self, symbols: list[str], filing_type: str = "consolidated") -> dict:
        return self._call("compute_rankings", {
            "symbols": symbols, "filing_type": filing_type, "db_path": self.db_path,
        })

    def compute_financial_health(self, company: str, filing_type: str = "consolidated") -> dict:
        return self._call("compute_financial_health", {"company": company, "filing_type": filing_type})

    def compute_company_report(self, symbol: str, peer_symbols: list[str],
                                filing_type: str = "consolidated") -> dict:
        return self._call("compute_company_report", {
            "symbol": symbol, "peer_symbols": peer_symbols,
            "filing_type": filing_type, "db_path": self.db_path,
        })

    def analyze_trends(self, company: str, filing_type: str = "consolidated") -> dict:
        return self._call("analyze_trends", {"company": company, "filing_type": filing_type})

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> "AnalysisBridge":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
