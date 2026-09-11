
from __future__ import annotations

import json
import sys
from typing import Any, Callable, TextIO


def install_protocol_stdout() -> TextIO:
    real_stdout = sys.stdout
    sys.stdout = sys.stderr
    return real_stdout


def read_request(stream: TextIO = sys.stdin) -> dict | None:
    """Blocking read of one request line. Returns None at EOF (the client
    closed the pipe -- the worker should exit)."""
    line = stream.readline()
    if not line:
        return None
    line = line.strip()
    if not line:
        return read_request(stream)
    return json.loads(line)


def write_response(real_stdout: TextIO, request_id: int, *, result: Any = None,
                    error: str | None = None) -> None:
    payload: dict = {"id": request_id, "ok": error is None}
    if error is None:
        payload["result"] = result
    else:
        payload["error"] = error
    real_stdout.write(json.dumps(payload, default=str) + "\n")
    real_stdout.flush()


def run_worker_loop(real_stdout: TextIO, dispatch: Callable[[str, dict], Any]) -> None:
    while True:
        request = read_request()
        if request is None:
            return
        request_id = request.get("id")
        try:
            result = dispatch(request["command"], request.get("params") or {})
            write_response(real_stdout, request_id, result=result)
        except Exception as exc:  # noqa: BLE001 -- a worker must never crash silently on one bad request
            write_response(real_stdout, request_id, error=f"{type(exc).__name__}: {exc}")
