"""
the LLM Router itself 

    Query Router
         |
    -----+-----+-----
    |          |     |
  Simple    Numeric  Complex
    |          |     |
 Ollama  Financial Engine  Cloud LLM

"""
from __future__ import annotations

import logging
from typing import Optional

from .base import LLMClient, LLMResponse
from .cloud_client import ClaudeCloudClient
from .config import LLMConfig
from .errors import LLMBudgetExceededError, LLMConfigError, LLMUnavailableError
from .groq_client import GroqClient
from .ollama_client import OllamaClient

logger = logging.getLogger(__name__)

_RECOVERABLE = (LLMUnavailableError, LLMConfigError, LLMBudgetExceededError)

_CLOUD_CLIENT_CLASSES: dict[str, type] = {
    "anthropic": ClaudeCloudClient,
    "groq": GroqClient,
}


class LLMRouter:
    def __init__(self, config: LLMConfig):
        self.config = config
        self._local: Optional[LLMClient] = None
        self._cloud: Optional[LLMClient] = None
        self._cloud_init_error: Optional[Exception] = None

    def _get_local(self) -> LLMClient:
        if self._local is None:
            self._local = OllamaClient(
                model=self.config.local.model,
                base_url=self.config.local.base_url,
                timeout_s=self.config.local.timeout_s,
            )
        return self._local

    def _get_cloud(self) -> LLMClient:
        if self._cloud is not None:
            return self._cloud
        if self._cloud_init_error is not None:
            raise self._cloud_init_error
        if not self.config.cloud.enabled:
            err = LLMConfigError("llm.cloud.enabled is false in llm_config.yaml -- cloud calls are disabled.")
            self._cloud_init_error = err
            raise err

        client_cls = _CLOUD_CLIENT_CLASSES.get(self.config.cloud.provider)
        if client_cls is None:
            # Shouldn't happen -- config.py's _build_cloud_config() already validates
            # cloud.provider against the same provider set. Defensive, not load-bearing.
            err = LLMConfigError(
                f"cloud.provider={self.config.cloud.provider!r} has no registered client class "
                f"-- known providers: {sorted(_CLOUD_CLIENT_CLASSES)}."
            )
            self._cloud_init_error = err
            raise err

        try:
            cloud_kwargs = dict(
                model=self.config.cloud.model,
                api_key_env=self.config.cloud.api_key_env,
                timeout_s=self.config.cloud.timeout_s,
                max_tokens_default=self.config.cloud.max_tokens,
                max_calls_per_process=self.config.cloud.max_calls_per_process,
            )
            if client_cls is GroqClient:
                cloud_kwargs["tpm_limit"] = self.config.cloud.tpm_limit
                cloud_kwargs["tpd_limit"] = self.config.cloud.tpd_limit
            self._cloud = client_cls(**cloud_kwargs)
        except LLMConfigError as e:
            self._cloud_init_error = e
            raise
        return self._cloud

    def provider_for_task(self, task_type: str) -> str:
        return self.config.tasks.get(task_type, self.config.default_provider)

    def generate_for_task(
        self,
        task_type: str,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        primary = self.provider_for_task(task_type)
        secondary = "local" if primary == "cloud" else "cloud"

        try:
            return self._dispatch(primary, task_type, prompt, system, max_tokens, temperature)
        except _RECOVERABLE as primary_error:
            fallback_allowed = (
                (primary == "cloud" and self.config.cloud.fallback_to_local_on_error)
                or (primary == "local" and self.config.local.fallback_to_cloud_on_error)
            )
            if not fallback_allowed:
                raise
            logger.warning(
                "LLM task=%s primary=%s failed (%s); falling back to %s",
                task_type, primary, primary_error, secondary,
            )
            try:
                return self._dispatch(secondary, task_type, prompt, system, max_tokens, temperature)
            except _RECOVERABLE as fallback_error:
                # Both providers failed -- raise the fallback's error (it's the more recent /
                # more informative one), but don't lose the primary's error entirely.
                raise LLMUnavailableError(
                    fallback_error.provider if isinstance(fallback_error, LLMUnavailableError) else secondary,
                    f"Both providers failed for task '{task_type}'. Primary ({primary}): "
                    f"{primary_error}. Fallback ({secondary}): {fallback_error}.",
                    cause=fallback_error,
                ) from fallback_error

    def _dispatch(
        self,
        provider: str,
        task_type: str,
        prompt: str,
        system: Optional[str],
        max_tokens: Optional[int],
        temperature: float,
    ) -> LLMResponse:
        client = self._get_local() if provider == "local" else self._get_cloud()
        return client.generate(
            prompt, system=system, max_tokens=max_tokens or 1024, temperature=temperature, task_type=task_type,
        )