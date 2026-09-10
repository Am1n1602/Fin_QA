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
