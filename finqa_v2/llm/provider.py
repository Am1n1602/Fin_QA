"""LLMProvider protocol + a direct Groq implementation (OpenAI-compatible endpoint)
with a client-side rate/usage guard for the free tier (see limits.py).

Deliberately thin. v1's llm_router (Ollama fallback, task routing) can be adapted to
this protocol later; the v2 reasoning stack only needs `complete(...) -> str`.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Protocol, runtime_checkable

from finqa_v2.llm.limits import (
    CostBudget,
    LLMBudgetExceededError,
    RateBudget,
    estimate_tokens,
)

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_DEFAULT_MODEL = "openai/gpt-oss-120b"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, prompt: str, *, system: str | None = None, json_object: bool = False,
                 temperature: float = 0.1, max_tokens: int = 1024) -> str:
        """Return the model's text. When json_object=True the text is a JSON object."""


class NullProvider:
    """No LLM available. Every call raises -- callers fall back to deterministic paths."""

    name = "null"

    def complete(self, prompt, *, system=None, json_object=False, temperature=0.1, max_tokens=1024):
        raise LLMError("no LLM provider configured")


def _read_dotenv_text(path: pathlib.Path) -> str:
    """PowerShell's `>>` / `Out-File` writes .env as UTF-16 with a BOM by default (not
    UTF-8) -- decode defensively rather than crash on a Windows-created file."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_env_key(name: str = "GROQ_API_KEY") -> str | None:
    key = os.environ.get(name)
    if key:
        return key.strip()
    env = pathlib.Path(".env")
    if env.exists():
        for line in _read_dotenv_text(env).splitlines():
            line = line.strip()
            if line.startswith(f"{name}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


class GroqProvider:
    name = "groq"

    def __init__(self, *, api_key: str | None = None, model: str = _DEFAULT_MODEL,
                 timeout: float = 45.0, budget: RateBudget | None = None,
                 max_retries: int = 1):
        self.api_key = api_key or _read_env_key()
        if not self.api_key:
            raise LLMError("GROQ_API_KEY not found (environment or .env)")
        self.model = model
        self.timeout = timeout
        self.budget = budget if budget is not None else RateBudget.from_env()
        self.max_retries = max_retries
        self.last_headers: dict[str, str] = {}

    @property
    def usage(self) -> dict:
        return self.budget.usage

    def complete(self, prompt: str, *, system: str | None = None, json_object: bool = False,
                 temperature: float = 0.1, max_tokens: int = 1024) -> str:
        import requests

        est = estimate_tokens(prompt, system, max_tokens)
        self.budget.check_and_reserve(est)   # may sleep (RPM/TPM) or raise (session/TPD)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {"model": self.model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens}
        if json_object:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        attempt = 0
        while True:
            try:
                r = requests.post(_GROQ_URL, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                raise LLMError(f"groq request failed: {e}") from e

            self.last_headers = {k.lower(): v for k, v in r.headers.items()
                                 if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"}

            if r.status_code == 429:
                if attempt >= self.max_retries:
                    raise LLMBudgetExceededError(
                        f"groq 429 (rate limited) after {attempt + 1} attempt(s). "
                        f"headers: {self.last_headers}"
                    )
                wait = _retry_after_seconds(self.last_headers)
                self.budget.sleep(wait)
                attempt += 1
                continue

            if not r.ok:
                raise LLMError(f"groq HTTP {r.status_code}: {r.text[:300]}")

            try:
                data = r.json()
                text = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                raise LLMError(f"unexpected groq response: {e}") from e

            usage = data.get("usage") or {}
            self.budget.record(usage.get("prompt_tokens", est), usage.get("completion_tokens", 0))
            return text


class AnthropicProvider:
    """Direct Claude API (Messages endpoint), guarded by a hard dollar cap (`CostBudget`)
    instead of Groq's free-tier request/token windows -- appropriate for a paid key with a
    known, finite balance. Reads `ANTHROPIC_API_KEY` from the environment or `.env`.
    """

    name = "anthropic"

    def __init__(self, *, api_key: str | None = None, model: str = _DEFAULT_ANTHROPIC_MODEL,
                 timeout: float = 60.0, budget: CostBudget | None = None, max_retries: int = 2):
        self.api_key = api_key or _read_env_key("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY not found (environment or .env)")
        self.model = model
        self.timeout = timeout
        self.budget = budget if budget is not None else CostBudget.from_env()
        self.max_retries = max_retries

    @property
    def usage(self) -> dict:
        return self.budget.usage

    def complete(self, prompt: str, *, system: str | None = None, json_object: bool = False,
                 temperature: float = 0.1, max_tokens: int = 1024) -> str:
        import requests

        # chars//4 undercounts real tokenization on number-dense financial text (digits and
        # punctuation split less efficiently); pad the pre-call estimate so the cost GATE
        # never lets a call through that the real, post-call usage would push over budget.
        est_prompt_tokens = int((len(prompt or "") + len(system or "")) // 4 * 1.35)
        self.budget.check_and_reserve(self.model, est_prompt_tokens, max_tokens)

        sys_text = system or ""
        if json_object:
            sys_text = (sys_text + "\n\nRespond with a single JSON object only -- no prose, "
                       "no markdown code fences.").strip()
        # `temperature` is deprecated/rejected by the Claude 5 family's Messages API --
        # omit it rather than pin sampling; the prompts already ask explicitly for JSON.
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}]}
        if sys_text:
            body["system"] = sys_text
        headers = {"x-api-key": self.api_key, "anthropic-version": _ANTHROPIC_VERSION,
                  "content-type": "application/json"}

        attempt = 0
        while True:
            try:
                r = requests.post(_ANTHROPIC_URL, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                raise LLMError(f"anthropic request failed: {e}") from e

            if r.status_code == 429:
                if attempt >= self.max_retries:
                    raise LLMBudgetExceededError(
                        f"anthropic 429 (rate limited) after {attempt + 1} attempt(s).")
                wait = _retry_after_seconds({k.lower(): v for k, v in r.headers.items()})
                time.sleep(wait)
                attempt += 1
                continue

            if not r.ok:
                raise LLMError(f"anthropic HTTP {r.status_code}: {r.text[:300]}")

            try:
                data = r.json()
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text")
            except (KeyError, json.JSONDecodeError) as e:
                raise LLMError(f"unexpected anthropic response: {e}") from e

            usage = data.get("usage") or {}
            self.budget.record(self.model, usage.get("input_tokens", est_prompt_tokens),
                               usage.get("output_tokens", 0))
            return text


def _retry_after_seconds(headers: dict[str, str], default: float = 2.0, cap: float = 30.0) -> float:
    for k in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        v = headers.get(k)
        if not v:
            continue
        try:
            secs = float(v.rstrip("s"))
            return min(cap, max(0.5, secs))
        except ValueError:
            continue
    return default


def provider_from_env(*, model: str = _DEFAULT_MODEL, budget: RateBudget | None = None) -> LLMProvider:
    """GroqProvider (sharing `budget` if given) when a key is available and the LLM is not
    disabled via FINQA_LLM_DISABLED=1; otherwise NullProvider."""
    if os.environ.get("FINQA_LLM_DISABLED") == "1":
        return NullProvider()
    try:
        return GroqProvider(model=model, budget=budget)
    except LLMError:
        return NullProvider()


def anthropic_provider_from_env(*, model: str = _DEFAULT_ANTHROPIC_MODEL,
                                budget: CostBudget | None = None) -> LLMProvider:
    """AnthropicProvider (sharing `budget` if given) when ANTHROPIC_API_KEY is available
    and the LLM is not disabled via FINQA_LLM_DISABLED=1; otherwise NullProvider. Separate
    from `provider_from_env` (Groq) so choosing the paid Claude path is always explicit."""
    if os.environ.get("FINQA_LLM_DISABLED") == "1":
        return NullProvider()
    try:
        return AnthropicProvider(model=model, budget=budget)
    except LLMError:
        return NullProvider()
