"""Client-side rate + usage guard for the Groq free tier.

Evolves llm_router/llm/groq_client.py's approach: a sliding 60-second window that
*sleeps* to stay under requests-per-minute and tokens-per-minute, plus hard session
and daily caps that *raise* (so an accidental eval run can never blow the daily quota).
Groq's own `x-ratelimit-*` response headers are trusted over our estimate when present.

Free-tier defaults are conservative (below Groq's published gpt-oss-120b limits) and
override via env: FINQA_LLM_MAX_REQUESTS, FINQA_LLM_RPM, FINQA_LLM_TPM, FINQA_LLM_TPD.
Set FINQA_LLM_DISABLED=1 to force NullProvider (spend nothing).
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from finqa_v2.observability.metrics import record_llm_usage


class LLMBudgetExceededError(RuntimeError):
    """Raised when a hard cap (session request count or tokens-per-day) is hit."""


def estimate_tokens(prompt: str, system: str | None, max_tokens: int) -> int:
    return (len(prompt or "") + len(system or "")) // 4 + max_tokens


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "")) or default
    except ValueError:
        return default


@dataclass
class RateBudget:
    max_requests: int = 60          # hard per-process/session cap (raises)
    rpm_limit: int = 25             # requests/min (sleeps)
    tpm_limit: int = 7_000         # tokens/min (sleeps)
    tpd_limit: int = 180_000       # tokens/day (raises)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    requests_made: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tokens_today: int = 0
    _window: deque = field(default_factory=deque)   # (ts, token_count) within the last 60 s

    # ------------------------------------------------------------------ #
    @classmethod
    def from_env(cls) -> "RateBudget":
        return cls(
            max_requests=_env_int("FINQA_LLM_MAX_REQUESTS", 60),
            rpm_limit=_env_int("FINQA_LLM_RPM", 25),
            tpm_limit=_env_int("FINQA_LLM_TPM", 7_000),
            tpd_limit=_env_int("FINQA_LLM_TPD", 180_000),
        )

    # ------------------------------------------------------------------ #
    def _prune(self, now: float) -> None:
        while self._window and now - self._window[0][0] >= 60.0:
            self._window.popleft()

    def _sleep_until_oldest_expires(self, now: float) -> None:
        if not self._window:
            return
        wait = max(0.0, 60.0 - (now - self._window[0][0]) + 0.05)
        if wait > 0:
            self.sleep(wait)

    def check_and_reserve(self, est_tokens: int) -> None:
        if self.requests_made >= self.max_requests:
            raise LLMBudgetExceededError(
                f"session LLM request cap reached ({self.max_requests}). Raise "
                f"FINQA_LLM_MAX_REQUESTS or start a new process."
            )
        if self.tokens_today + est_tokens > self.tpd_limit:
            raise LLMBudgetExceededError(
                f"this call (~{est_tokens:,} est. tokens) would exceed the tokens-per-day cap "
                f"({self.tokens_today:,} used + this > {self.tpd_limit:,}). Check "
                f"https://console.groq.com for real remaining quota."
            )
        now = self.clock()
        self._prune(now)
        if len(self._window) >= self.rpm_limit:
            self._sleep_until_oldest_expires(now)
            now = self.clock()
            self._prune(now)
        window_tokens = sum(t for _, t in self._window)
        if self._window and window_tokens + est_tokens > self.tpm_limit:
            self._sleep_until_oldest_expires(now)
            self._prune(self.clock())

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        total = (prompt_tokens or 0) + (completion_tokens or 0)
        self.requests_made += 1
        self.prompt_tokens += prompt_tokens or 0
        self.completion_tokens += completion_tokens or 0
        self.tokens_today += total
        self._window.append((self.clock(), total or 1))
        # RateBudget is only ever used for the Groq free-tier path (see module docstring).
        record_llm_usage("groq", prompt_tokens=prompt_tokens or 0, completion_tokens=completion_tokens or 0)

    # ------------------------------------------------------------------ #
    @property
    def usage(self) -> dict:
        return {
            "requests_made": self.requests_made,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "tokens_today": self.tokens_today,
            "requests_remaining": max(0, self.max_requests - self.requests_made),
            "tpd_remaining": max(0, self.tpd_limit - self.tokens_today),
        }


# $ per 1M (input, output) tokens. Verify at https://claude.com/pricing before relying on
# this for a large run -- pricing can change.
ANTHROPIC_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}


@dataclass
class CostBudget:
    """Hard dollar cap for a paid provider (e.g. the Claude API) -- the analogue of
    RateBudget for a per-request-billed key instead of a shared free tier. Estimates the
    cost of a call BEFORE sending it and refuses (raises LLMBudgetExceededError) rather
    than risk exceeding `max_cost_usd`; `record()` reconciles against the real usage the
    API returns."""

    max_cost_usd: float = 3.0
    pricing: dict[str, tuple[float, float]] = field(
        default_factory=lambda: dict(ANTHROPIC_PRICING_PER_MTOK))

    spent_usd: float = 0.0
    requests_made: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @classmethod
    def from_env(cls, *, default_cap: float = 3.0) -> "CostBudget":
        try:
            cap = float(os.environ.get("FINQA_LLM_MAX_COST_USD", "") or default_cap)
        except ValueError:
            cap = default_cap
        return cls(max_cost_usd=cap)

    def _rate(self, model: str) -> tuple[float, float]:
        return self.pricing.get(model, (0.0, 0.0))

    def estimate_cost(self, model: str, prompt_tokens_est: int, max_tokens: int) -> float:
        rate_in, rate_out = self._rate(model)
        return prompt_tokens_est / 1e6 * rate_in + max_tokens / 1e6 * rate_out

    def check_and_reserve(self, model: str, prompt_tokens_est: int, max_tokens: int) -> None:
        est = self.estimate_cost(model, prompt_tokens_est, max_tokens)
        if self.spent_usd + est > self.max_cost_usd:
            raise LLMBudgetExceededError(
                f"this call (~${est:.4f} est., worst case at max_tokens={max_tokens}) would "
                f"exceed the cost cap (${self.spent_usd:.4f} spent + this > "
                f"${self.max_cost_usd:.2f}). Raise FINQA_LLM_MAX_COST_USD or start a new run."
            )

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        rate_in, rate_out = self._rate(model)
        cost = prompt_tokens / 1e6 * rate_in + completion_tokens / 1e6 * rate_out
        self.spent_usd += cost
        self.requests_made += 1
        self.prompt_tokens += prompt_tokens or 0
        self.completion_tokens += completion_tokens or 0
        # CostBudget is only ever used for the Anthropic paid path (see class docstring).
        record_llm_usage("anthropic", prompt_tokens=prompt_tokens or 0,
                         completion_tokens=completion_tokens or 0, cost_usd=cost)

    @property
    def usage(self) -> dict:
        return {
            "requests_made": self.requests_made,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "spent_usd": round(self.spent_usd, 4),
            "cap_usd": self.max_cost_usd,
            "remaining_usd": round(max(0.0, self.max_cost_usd - self.spent_usd), 4),
        }
