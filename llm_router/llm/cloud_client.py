from __future__ import annotations

import os
import time
from typing import Optional

from .base import LLMClient, LLMResponse
from .errors import LLMBudgetExceededError, LLMConfigError, LLMUnavailableError


class ClaudeCloudClient(LLMClient):
    provider_name = "anthropic"

    def __init__(
        self,
        model: str,
        api_key_env: str = "ANTHROPIC_API_KEY",
        timeout_s: int = 60,
        max_tokens_default: int = 1024,
        max_calls_per_process: Optional[int] = 200,
    ):
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise LLMConfigError(
                f"{api_key_env} is not set. The cloud client only ever reads an API key from this "
                f"environment variable -- never from llm_config.yaml. Set it in your shell/venv "
                f"activation before running a task routed to cloud, or set llm.cloud.enabled: false "
                f"in llm_config.yaml to run local-only."
            )
        try:
            import anthropic  # noqa: F401 (imported for its side effect of raising ImportError cleanly)
            from anthropic import Anthropic
        except ImportError as e:
            raise LLMConfigError(
                "The 'anthropic' package is not installed. Run: pip install anthropic "
                "(or set llm.cloud.enabled: false in llm_config.yaml to avoid needing it)."
            ) from e

        self._client = Anthropic(api_key=api_key, timeout=timeout_s)
        self.model = model
        self.max_tokens_default = max_tokens_default
        self.max_calls_per_process = max_calls_per_process
        self._calls_made = 0

    def is_available(self) -> bool:
        return True

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
                f"Cloud LLM call budget ({self.max_calls_per_process} calls) exhausted for this "
                f"process -- see llm.cloud.max_calls_per_process in llm_config.yaml. This is a crude "
                f"runaway-cost guard, not a real spend tracker; raise the limit or restart the "
                f"process to continue, and check whether something is calling cloud far more than "
                f"expected first."
            )

        request_kwargs = dict(
            model=self.model,
            max_tokens=max_tokens or self.max_tokens_default,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )

        t0 = time.monotonic()
        try:
            resp = self._create_message(request_kwargs, temperature)
        except Exception as e:
            raise LLMUnavailableError("anthropic", f"Cloud LLM call failed: {e}", cause=e) from e

        self._calls_made += 1
        latency_ms = (time.monotonic() - t0) * 1000

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        ).strip()
        if not text:
            raise LLMUnavailableError(
                "anthropic", f"Cloud LLM returned no text content (stop_reason={resp.stop_reason!r})."
            )

        usage = getattr(resp, "usage", None)
        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model,
            task_type=task_type,
            latency_ms=latency_ms,
            prompt_tokens=getattr(usage, "input_tokens", None),
            completion_tokens=getattr(usage, "output_tokens", None),
            raw=None,  # the SDK's response object isn't reliably JSON-serializable across versions
        )

    def _create_message(self, request_kwargs: dict, temperature: float):
        try:
            return self._client.messages.create(extra_body={"temperature": temperature}, **request_kwargs)
        except TypeError as e:
            if "extra_body" not in str(e) and "temperature" not in str(e):
                raise
            return self._client.messages.create(temperature=temperature, **request_kwargs)
        except Exception as e:
            if "temperature" in str(e).lower() or "sampling" in str(e).lower():
                return self._client.messages.create(**request_kwargs)
            raise