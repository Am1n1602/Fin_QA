"""Prometheus metrics for finqa_v2 (Phase 25). One process-wide registry; every metric
here is written from an existing choke point (ToolRegistry.call, RateBudget/CostBudget
.record, Verifier._adjudicate) rather than a new parallel accounting path, so what you
see in Grafana is the same numbers already used internally, not a separate estimate.

Import is optional at the call site: every `record_*`/`set_*` function is a no-op if
`prometheus_client` isn't installed (base install doesn't require the `observability`
extra), so nothing outside this module needs an if-installed check.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("finqa.v2.observability")

try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest

    _AVAILABLE = True
except ImportError:  # pragma: no cover -- exercised by test_metrics.py's skip path
    _AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain"

REGISTRY = CollectorRegistry() if _AVAILABLE else None

if _AVAILABLE:
    HTTP_REQUESTS = Counter(
        "finqa_http_requests_total", "HTTP requests by route template, method, and status",
        ["method", "path", "status"], registry=REGISTRY,
    )
    HTTP_LATENCY = Histogram(
        "finqa_http_request_duration_seconds", "HTTP request latency by route template",
        ["method", "path"], registry=REGISTRY,
    )
    TOOL_CALLS = Counter(
        "finqa_tool_calls_total", "Tool Registry calls by tool name and outcome",
        ["tool", "status"], registry=REGISTRY,
    )
    TOOL_LATENCY = Histogram(
        "finqa_tool_call_duration_seconds", "Tool Registry call latency by tool name",
        ["tool"], registry=REGISTRY,
    )
    LLM_REQUESTS = Counter(
        "finqa_llm_requests_total", "LLM provider calls by provider",
        ["provider"], registry=REGISTRY,
    )
    LLM_TOKENS = Counter(
        "finqa_llm_tokens_total", "LLM tokens by provider and kind (prompt/completion)",
        ["provider", "kind"], registry=REGISTRY,
    )
    LLM_COST_USD = Counter(
        "finqa_llm_cost_usd_total", "Estimated LLM spend in USD by provider (0 for free-tier providers)",
        ["provider"], registry=REGISTRY,
    )
    VERIFICATION_STATUS = Counter(
        "finqa_verification_status_total", "Verifier.verify() outcomes by status",
        ["status"], registry=REGISTRY,
    )
    EVAL_BASELINE_ACCURACY = Gauge(
        "finqa_eval_baseline_accuracy", "Pinned regression-gate baseline accuracy by metric "
        "(refreshed from disk on every /metrics scrape -- reflects the last time someone ran "
        "the eval + regression gate and updated the pinned baseline, not a live continuous run)",
        ["metric"], registry=REGISTRY,
    )
    EVAL_BASELINE_INFO = Gauge(
        "finqa_eval_baseline_info", "1, labelled with the pinned baseline's label/git_commit/generated_at",
        ["label", "git_commit", "generated_at"], registry=REGISTRY,
    )
    CACHE_EVENTS = Counter(
        "finqa_answer_cache_events_total", "In-process /qa and /research answer-cache lookups by outcome",
        ["cache", "outcome"], registry=REGISTRY,
    )


def record_tool_call(tool: str, ok: bool, latency_ms: float) -> None:
    if not _AVAILABLE:
        return
    TOOL_CALLS.labels(tool=tool, status="ok" if ok else "error").inc()
    TOOL_LATENCY.labels(tool=tool).observe(latency_ms / 1000.0)


def record_llm_usage(provider: str, *, prompt_tokens: int, completion_tokens: int,
                     cost_usd: float = 0.0) -> None:
    if not _AVAILABLE:
        return
    LLM_REQUESTS.labels(provider=provider).inc()
    LLM_TOKENS.labels(provider=provider, kind="prompt").inc(max(0, prompt_tokens or 0))
    LLM_TOKENS.labels(provider=provider, kind="completion").inc(max(0, completion_tokens or 0))
    if cost_usd:
        LLM_COST_USD.labels(provider=provider).inc(cost_usd)


def record_cache_event(cache: str, hit: bool) -> None:
    if not _AVAILABLE:
        return
    CACHE_EVENTS.labels(cache=cache, outcome="hit" if hit else "miss").inc()


def record_verification(status: str) -> None:
    if not _AVAILABLE:
        return
    VERIFICATION_STATUS.labels(status=status).inc()


def record_http_request(method: str, path: str, status: int, duration_s: float) -> None:
    if not _AVAILABLE:
        return
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, path=path).observe(duration_s)


def _accuracy(section) -> float | None:
    if not isinstance(section, dict):
        return None
    if "accuracy" in section:
        return section["accuracy"]
    verdict = section.get("verdict")
    return verdict.get("accuracy") if isinstance(verdict, dict) else None


_BASELINE_METRICS = ("intent_match", "numerical", "correctness", "groundedness",
                    "unsupported_claims", "abstention")


def refresh_eval_baseline_gauges(baseline_path: Path) -> dict[str, float]:
    """Reads the pinned regression-gate baseline (evaluation/regression/baselines/*.json,
    see evaluation/regression/compare.py) and sets the eval-monitoring gauges from it.
    Returns the values set (mainly for tests); silently does nothing if the file is
    missing or unreadable -- a stale/absent baseline shouldn't break /metrics."""
    if not _AVAILABLE:
        return {}
    try:
        report = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("could not read eval baseline at %s: %s", baseline_path, e)
        return {}

    agg = report.get("aggregates", {})
    values: dict[str, float] = {}
    for name in _BASELINE_METRICS:
        acc = _accuracy(agg.get(name))
        if acc is not None:
            values[name] = acc

    citation = agg.get("citation") or {}
    if "mean_precision" in citation:
        values["citation_precision"] = citation["mean_precision"]
        values["citation_recall"] = citation.get("mean_recall", 0.0)

    for metric, value in values.items():
        EVAL_BASELINE_ACCURACY.labels(metric=metric).set(value)
    EVAL_BASELINE_INFO.labels(
        label=str(report.get("label", "")),
        git_commit=str(report.get("git_commit", ""))[:12],
        generated_at=str(report.get("generated_at", "")),
    ).set(1)
    return values


def render_latest() -> bytes:
    if not _AVAILABLE:
        return b"# prometheus_client is not installed -- install the 'observability' extra\n"
    return generate_latest(REGISTRY)
