from __future__ import annotations

import os
import time
from collections import deque
from typing import Optional

import requests

from .base import LLMClient, LLMResponse
from .errors import LLMBudgetExceededError, LLMConfigError, LLMUnavailableError


class GroqClient(LLMClient):
    provider_name = "groq"

    _ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        model: str,
        api_key_env: str = "GROQ_API_KEY",
        timeout_s: int = 60,
        max_tokens_default: int = 1024,
        max_calls_per_process: Optional[int] = None,
        tpm_limit: Optional[int] = None,
        tpd_limit: Optional[int] = None,
    ):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMConfigError(
                f"{api_key_env} is not set. The Groq client only ever reads an API key from this "
                f"environment variable -- never from llm_config.yaml. Get a free key at "
                f"https://console.groq.com/keys (no credit card required), then set it in your "
                f"shell/venv activation."
            )
        self._api_key = api_key
        self.model = model
        self.timeout_s = timeout_s
        self.max_tokens_default = max_tokens_default
        self.max_calls_per_process = max_calls_per_process
        self._calls_made = 0

        self.tpm_limit = tpm_limit
        self.tpd_limit = tpd_limit
        self._minute_window: deque = deque()  # (monotonic_timestamp, token_count) pairs, last 60s
        self._tokens_today = 0

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _estimate_tokens(prompt: str, system: Optional[str], max_tokens: int) -> int:

        input_chars = len(prompt or "") + len(system or "")
        return (input_chars // 4) + max_tokens

    def _wait_for_tpm_budget(self, estimated_tokens: int) -> None:

        if self.tpm_limit is None:
            return
        now = time.monotonic()
        while self._minute_window and now - self._minute_window[0][0] >= 60:
            self._minute_window.popleft()
        window_tokens = sum(tokens for _, tokens in self._minute_window)
        if window_tokens + estimated_tokens <= self.tpm_limit:
            return
        if not self._minute_window:
            return
        sleep_for = max(0.0, 60 - (now - self._minute_window[0][0]) + 0.1)
        if sleep_for > 0:
            time.sleep(sleep_for)
        now = time.monotonic()
        while self._minute_window and now - self._minute_window[0][0] >= 60:
            self._minute_window.popleft()

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
        task_type: Optional[str] = None,
    ) -> LLMResponse:
        if self.max_calls_per_process is not None and self._calls_made >= self.max_calls_per_process:
            raise LLMBudgetExceededError(
                f"Groq call budget ({self.max_calls_per_process} calls) exhausted for this "
                f"process -- see llm.cloud.max_calls_per_process in llm_config.yaml. Groq's own "
                f"free-tier daily limits are separate, provider-side caps this coarse guard does "
                f"not track precisely -- see tpm_limit/tpd_limit below for the ones that actually "
                f"bind first for this app's prompts, or check https://console.groq.com for your "
                f"actual remaining quota."
            )

        effective_max_tokens = max_tokens or self.max_tokens_default
        estimated_tokens = self._estimate_tokens(prompt, system, effective_max_tokens)

        if self.tpd_limit is not None and self._tokens_today + estimated_tokens > self.tpd_limit:
            raise LLMBudgetExceededError(
                f"This call (~{estimated_tokens:,} estimated tokens) would exceed Groq's free-tier "
                f"tokens-per-day budget (~{self._tokens_today:,} used so far this process + this "
                f"call > {self.tpd_limit:,} tpd_limit). This is the REAL binding daily constraint "
                f"for this app's prompts (see this module's docstring) -- not request count alone. "
                f"Falls back to local per llm.cloud.fallback_to_local_on_error like any other "
                f"budget error."
            )

        self._wait_for_tpm_budget(estimated_tokens)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": effective_max_tokens,
            "temperature": temperature,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

        t0 = time.monotonic()
        try:
            resp = requests.post(self._ENDPOINT, json=payload, headers=headers, timeout=self.timeout_s)
            resp.raise_for_status()
        except requests.RequestException as e:
            detail = ""
            if getattr(e, "response", None) is not None:
                try:
                    detail = f" -- {e.response.json()}"
                except ValueError:
                    detail = f" -- {e.response.text[:300]}"
            raise LLMUnavailableError("groq", f"Groq API call failed: {e}{detail}", cause=e) from e
        latency_ms = (time.monotonic() - t0) * 1000

        try:
            data = resp.json()
        except ValueError as e:
            raise LLMUnavailableError("groq", f"Groq returned a non-JSON response body: {e}", cause=e) from e

        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailableError("groq", f"Unexpected Groq response shape: {data}", cause=e) from e

        if not text:
            raise LLMUnavailableError("groq", f"Groq returned an empty response body for model '{self.model}'.")

        self._calls_made += 1
        usage = data.get("usage") or {}
        actual_tokens = usage.get("total_tokens") or estimated_tokens
        self._tokens_today += actual_tokens
        self._minute_window.append((time.monotonic(), actual_tokens))
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=data.get("model", self.model),
            task_type=task_type,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            raw=data,
        )