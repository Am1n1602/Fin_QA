from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

from .errors import LLMConfigError

try:
    import yaml
except ImportError as _e:  # pragma: no cover - exercised only if pyyaml truly isn't installed
    yaml = None
    _YAML_IMPORT_ERROR = _e
else:
    _YAML_IMPORT_ERROR = None

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "llm_config.yaml"

DEFAULT_TASK_MAP: dict[str, str] = {
    # Local (Ollama) -- small, fast, cheap, per roadmap Section 19.
    "classification": "local",
    "extraction": "local",
    "simple_summary": "local",
    "formatting": "local",
    # Cloud -- complex reasoning / synthesis, per roadmap Section 20-21.
    "narrative_synthesis": "cloud",
    "complex_qa": "cloud",
    "research_report": "cloud",
}

_VALID_PROVIDERS = ("local", "cloud")

_CLOUD_PROVIDER_DEFAULTS: dict[str, dict] = {
    "groq": {"model": "openai/gpt-oss-120b", "api_key_env": "GROQ_API_KEY"},
    "anthropic": {"model": "claude-sonnet-4-5-20250929", "api_key_env": "ANTHROPIC_API_KEY"},
}


@dataclass
class LocalLLMConfig:
    provider: str = "ollama"
    model: str = "llama3.2:3b"
    base_url: str = "http://localhost:11434"
    timeout_s: int = 60
    fallback_to_cloud_on_error: bool = True


@dataclass
class CloudLLMConfig:
    enabled: bool = True
    provider: str = "groq"
    model: str = "openai/gpt-oss-120b"
    api_key_env: str = "GROQ_API_KEY"
    timeout_s: int = 60
    max_tokens: int = 1024
    max_calls_per_process: Optional[int] = 200
    tpm_limit: Optional[int] = 8000
    tpd_limit: Optional[int] = 200000
    fallback_to_local_on_error: bool = True


@dataclass
class LLMConfig:
    default_provider: str = "local"
    local: LocalLLMConfig = field(default_factory=LocalLLMConfig)
    cloud: CloudLLMConfig = field(default_factory=CloudLLMConfig)
    tasks: dict = field(default_factory=lambda: dict(DEFAULT_TASK_MAP))


def _build_dataclass(cls, raw: dict, path: Path):
    valid_keys = {f.name for f in fields(cls)}
    for key in raw:
        if key not in valid_keys:
            raise LLMConfigError(
                f"Unknown key '{key}' under this section of {path} -- check for a typo. "
                f"Valid keys: {sorted(valid_keys)}."
            )
    defaults = cls()
    merged = {**defaults.__dict__, **raw}
    return cls(**merged)


def _build_cloud_config(cloud_raw: dict, path: Path) -> CloudLLMConfig:
    valid_keys = {f.name for f in fields(CloudLLMConfig)}
    for key in cloud_raw:
        if key not in valid_keys:
            raise LLMConfigError(
                f"Unknown key 'cloud.{key}' in {path} -- check for a typo. Valid keys: {sorted(valid_keys)}."
            )

    provider = cloud_raw.get("provider", CloudLLMConfig.provider)
    if provider not in _CLOUD_PROVIDER_DEFAULTS:
        raise LLMConfigError(
            f"cloud.provider = {provider!r} in {path} -- must be one of "
            f"{sorted(_CLOUD_PROVIDER_DEFAULTS)} (or add a new entry to "
            f"_CLOUD_PROVIDER_DEFAULTS in config.py and a matching client in router.py)."
        )

    defaults = {**CloudLLMConfig().__dict__, **_CLOUD_PROVIDER_DEFAULTS[provider], "provider": provider}
    merged = {**defaults, **cloud_raw}
    return CloudLLMConfig(**merged)


def load_llm_config(path: str | Path | None = None) -> LLMConfig:
    if path is not None:
        resolved_path = Path(path)
    else:
        resolved_path = Path(os.environ.get("LLM_ROUTER_CONFIG", DEFAULT_CONFIG_PATH))

    if not resolved_path.exists():
        return LLMConfig()

    if yaml is None:
        raise LLMConfigError(
            f"pyyaml is not installed but a config file exists at {resolved_path}. "
            f"Run: pip install pyyaml"
        ) from _YAML_IMPORT_ERROR

    with open(resolved_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    llm_raw = raw.get("llm", raw)
    if not isinstance(llm_raw, dict):
        raise LLMConfigError(f"{resolved_path} did not parse to a mapping under 'llm:' (or at the top level).")

    local_raw = llm_raw.get("local", {}) or {}
    cloud_raw = llm_raw.get("cloud", {}) or {}
    tasks_raw = llm_raw.get("tasks", {}) or {}
    default_provider = llm_raw.get("router", "local")

    if default_provider not in _VALID_PROVIDERS:
        raise LLMConfigError(
            f"llm.router = {default_provider!r} in {resolved_path} -- must be one of {_VALID_PROVIDERS}."
        )

    local = _build_dataclass(LocalLLMConfig, local_raw, resolved_path)
    cloud = _build_cloud_config(cloud_raw, resolved_path)

    tasks = {**DEFAULT_TASK_MAP, **tasks_raw}
    for task_name, provider in tasks.items():
        if provider not in _VALID_PROVIDERS:
            raise LLMConfigError(
                f"tasks.{task_name} = {provider!r} in {resolved_path} -- must be one of {_VALID_PROVIDERS}."
            )

    return LLMConfig(default_provider=default_provider, local=local, cloud=cloud, tasks=tasks)