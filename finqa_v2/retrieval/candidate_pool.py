"""Per-intent candidate pool size config (§20) -- loaded from YAML, never hardcoded in
retrieval logic. See finqa_v2/retrieval/candidate_pool.yaml for the actual sizes and
`HybridRetriever.retrieve(..., adaptive_pool=True)` for where it's applied."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("candidate_pool.yaml")


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get_candidate_k(intent: str | None, *, default: int, path: Path | str = DEFAULT_PATH) -> int:
    """`default` (the caller's own `candidate_k`) whenever `intent` is falsy, the config
    file is missing, or neither the intent nor a `default:` key in the config is set --
    so an unconfigured intent falls back to whatever the caller already asked for, not a
    hardcoded number."""
    if not intent:
        return default
    cfg = _load(str(path))
    if intent in cfg:
        return int(cfg[intent])
    if "default" in cfg:
        return int(cfg["default"])
    return default
