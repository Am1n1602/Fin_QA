"""Tool primitives: validation (pydantic) + latency + logging + error handling +
a call trace (§19, §27, §35). Tools never raise to the caller -- failures come back
as ToolResult(ok=False).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from finqa_v2.observability.metrics import record_tool_call

logger = logging.getLogger("finqa.v2.tools")


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool: str
    ok: bool
    value: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    evidence: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {
            "tool": self.tool, "ok": self.ok, "value": self.value,
            "error": self.error, "latency_ms": round(self.latency_ms, 2),
            "evidence": list(self.evidence),
        }


@dataclass(slots=True)
class ToolCall:
    tool: str
    args: dict
    ok: bool
    latency_ms: float
    error: str | None
    ts: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Tool:
    """Wraps `fn(model) -> value` or `fn(model) -> (value, list[evidence_dict])`."""

    def __init__(self, name: str, description: str, input_model: type[BaseModel],
                 fn: Callable[[BaseModel], Any]):
        self.name = name
        self.description = description
        self.input_model = input_model
        self._fn = fn

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema(),
        }

    def call(self, **raw: Any) -> ToolResult:
        t0 = perf_counter()
        try:
            data = self.input_model(**raw)
        except ValidationError as e:
            ms = (perf_counter() - t0) * 1000
            msg = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())
            logger.warning("tool=%s invalid_input args=%s err=%s", self.name, raw, msg)
            return ToolResult(self.name, False, error=f"invalid input: {msg}", latency_ms=ms)

        try:
            out = self._fn(data)
            if isinstance(out, tuple) and len(out) == 2 and isinstance(out[1], list):
                value, evidence = out
            else:
                value, evidence = out, []
            ms = (perf_counter() - t0) * 1000
            logger.info("tool=%s ok args=%s latency_ms=%.1f", self.name, raw, ms)
            return ToolResult(self.name, True, value=value, evidence=tuple(evidence), latency_ms=ms)
        except Exception as e:  # noqa: BLE001 -- tools must not raise to the caller
            ms = (perf_counter() - t0) * 1000
            logger.error("tool=%s error args=%s err=%s: %s", self.name, raw, type(e).__name__, e)
            return ToolResult(self.name, False, error=f"{type(e).__name__}: {e}", latency_ms=ms)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        self.trace: list[ToolCall] = []

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def add(self, name: str, description: str, input_model: type[BaseModel],
            fn: Callable[[BaseModel], Any]) -> None:
        self.register(Tool(name, description, input_model, fn))

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [self._tools[n].schema() for n in self.names()]

    def call(self, name: str, **kwargs: Any) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            res = ToolResult(name, False, error=f"unknown tool {name!r}")
        else:
            res = tool.call(**kwargs)
        self.trace.append(ToolCall(name, dict(kwargs), res.ok, res.latency_ms, res.error, _now()))
        record_tool_call(name, res.ok, res.latency_ms)
        return res

    def reset_trace(self) -> None:
        self.trace.clear()

    def trace_summary(self) -> dict:
        by_tool: dict[str, int] = {}
        for c in self.trace:
            by_tool[c.tool] = by_tool.get(c.tool, 0) + 1
        return {
            "n_calls": len(self.trace),
            "errors": sum(1 for c in self.trace if not c.ok),
            "total_latency_ms": round(sum(c.latency_ms for c in self.trace), 1),
            "by_tool": by_tool,
        }
