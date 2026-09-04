"""
qa_router/src/bridges/rag_bridge.py

"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.config import DB_PATH, DEVICE, EMBEDDING_MODEL_NAME, RAG_DIR, RAG_INDEX_DIR, RERANK_MODEL_NAME

_WORKER_SCRIPT = Path(__file__).with_name("rag_worker.py")


class RagBridge:
    def __init__(
        self,
        db_path: str | Path = DB_PATH,
        rag_dir: str | Path = RAG_DIR,
        index_dir: str | Path = RAG_INDEX_DIR,
        model_name: str = EMBEDDING_MODEL_NAME,
        rerank_model: str = RERANK_MODEL_NAME,
        device: str = DEVICE,
    ):
        self.db_path = str(db_path)
        self.rag_dir = str(rag_dir)
        self.index_dir = str(index_dir)
        self.model_name = model_name
        self.rerank_model = rerank_model
        self.device = device
        self._proc: subprocess.Popen | None = None
        self._next_id = 1

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        self._proc = subprocess.Popen(
            [
                sys.executable, str(_WORKER_SCRIPT),
                "--project-dir", self.rag_dir,
                "--db-path", self.db_path,
                "--index-dir", self.index_dir,
                "--model-name", self.model_name,
                "--rerank-model", self.rerank_model,
                "--device", self.device,
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=sys.stderr,
            text=True, bufsize=1,
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
                f"rag worker exited unexpectedly while handling '{command}' "
                f"(exit code {self._proc.poll()}). Check its stderr output above."
            )
        response = json.loads(line)
        if response["id"] != request_id:
            raise RuntimeError(f"rag worker response id mismatch: expected {request_id}, got {response['id']}")
        if not response["ok"]:
            raise RuntimeError(f"rag worker error on '{command}': {response['error']}")
        return response["result"]

    def retrieve(self, query: str, k: int = 5, company: str | None = None) -> list[dict]:
        return self._call("retrieve", {"query": query, "k": k, "company": company})

    def hybrid_retrieve(self, query: str, k: int = 5, company: str | None = None) -> list[dict]:
        return self._call("hybrid_retrieve", {"query": query, "k": k, "company": company})

    def reranked_retrieve(self, query: str, k: int = 5, company: str | None = None) -> list[dict]:
        return self._call("reranked_retrieve", {"query": query, "k": k, "company": company})

    def expanded_retrieve(
        self,
        query: str,
        expansions: list[str],
        k: int = 5,
        company: str | None = None,
        candidate_pool_per_variant: int = 30,
        final_pool_size: int = 50,
    ) -> list[dict]:
        """Like reranked_retrieve(), but the candidate pool is gathered
        using `query` PLUS each string in `expansions` (see
        query_expansion.py), then reranked against `query` alone. Use this
        instead of reranked_retrieve() whenever you have expansion
        variants to offer -- it strictly widens recall over a single-query
        search; passing expansions=[] behaves identically to
        reranked_retrieve() plus the extra id/rank bookkeeping."""
        return self._call("expanded_retrieve", {
            "query": query, "expansions": expansions, "k": k, "company": company,
            "candidate_pool_per_variant": candidate_pool_per_variant, "final_pool_size": final_pool_size,
        })

    def warm_up(self) -> None:
        try:
            self.reranked_retrieve("warmup", k=1, company=None)
        except Exception:  # noqa: BLE001 -- best-effort warm-up, never a new hard failure point
            pass

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> "RagBridge":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()