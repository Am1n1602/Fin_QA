"""Metrics, structured logging, and eval-baseline monitoring (§25). See docs/file-guide.md."""
from __future__ import annotations

from finqa_v2.observability.logging_config import configure_logging, new_request_id, request_id_var
from finqa_v2.observability.metrics import (
    record_http_request,
    record_llm_usage,
    record_tool_call,
    record_verification,
    refresh_eval_baseline_gauges,
    render_latest,
)

__all__ = [
    "configure_logging",
    "new_request_id",
    "request_id_var",
    "record_http_request",
    "record_llm_usage",
    "record_tool_call",
    "record_verification",
    "refresh_eval_baseline_gauges",
    "render_latest",
]
