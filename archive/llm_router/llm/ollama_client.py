"""
llm_router/llm/ollama_client.py -- local LLM client, talks to Ollama's
REST API directly over HTTP (no official Ollama Python package needed for
a single /api/generate call, one fewer dependency).
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from .base import LLMClient, LLMResponse
from .errors import LLMUnavailableError


class OllamaClient(LLMClient):
    provider_name = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout_s: int = 60):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def is_available(self) -> bool:
        """Cheap reachability check -- does NOT confirm `self.model` is pulled, only that a server answers."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        task_type: Optional[str] = None,
    ) -> LLMResponse:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system or "",
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        t0 = time.monotonic()
        try:
            resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=self.timeout_s)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise LLMUnavailableError(
                "ollama",
                f"Could not reach Ollama at {self.base_url} with model '{self.model}': {e}. "
                f"Is `ollama serve` running, and has `ollama pull {self.model}` been run?",
                cause=e,
            ) from e
        latency_ms = (time.monotonic() - t0) * 1000

        try:
            data = resp.json()
        except ValueError as e:
            raise LLMUnavailableError("ollama", f"Ollama returned a non-JSON response body: {e}", cause=e) from e

        text = (data.get("response") or "").strip()
        if not text:
            raise LLMUnavailableError(
                "ollama",
                f"Ollama returned an empty response body for model '{self.model}' "
                f"(full payload keys: {list(data.keys())}).",
            )

        return LLMResponse(
            text=text,
            provider=self.provider_name,
            model=self.model,
            task_type=task_type,
            latency_ms=latency_ms,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            raw=data,
        )
