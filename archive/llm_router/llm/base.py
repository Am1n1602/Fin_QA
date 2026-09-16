from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    task_type: Optional[str]
    latency_ms: float
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw: Optional[dict] = None


class LLMClient(ABC):
    provider_name: str = "unknown"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        task_type: Optional[str] = None,
    ) -> LLMResponse:
        raise NotImplementedError

    def is_available(self) -> bool:
        return True
