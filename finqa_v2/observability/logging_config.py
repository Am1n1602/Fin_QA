"""Structured logging + request-ID correlation (Phase 25's "tracing" for a single-service
deployment): every log line emitted while handling one API request carries the same
`request_id`, so grepping (or querying, once logs are shipped somewhere) for one ID gives
the request's full path across the API layer, the Tool Registry, and the LLM provider --
without standing up a separate distributed-tracing backend a system this size doesn't need.

    FINQA_V2_LOG_JSON=1   -- emit one JSON object per line instead of the default plain
                             text formatter (set this in production; plain text is easier
                             to read in a dev terminal).
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import uuid
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class RequestIdFilter(logging.Filter):
    """Attaches the current request's id (from `request_id_var`) to every log record so
    both formatters below can include it, whether or not the log call site knows it's
    running inside a request."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_PLAIN_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


def configure_logging(*, level: int = logging.INFO, json_logs: bool | None = None) -> None:
    """Call once at process startup (finqa_v2/api/main.py, worker entry points). Safe to
    call more than once -- clears and re-adds the root handler rather than stacking."""
    if json_logs is None:
        json_logs = os.environ.get("FINQA_V2_LOG_JSON") == "1"

    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if json_logs else logging.Formatter(_PLAIN_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)
