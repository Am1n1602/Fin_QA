"""Per-intent section weight config (§15) -- loaded from YAML, never hardcoded in
retrieval logic. See finqa_v2/retrieval/section_weights.yaml for the actual weights and
`HybridRetriever.retrieve(..., intent=...)` for where they're applied."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("section_weights.yaml")


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get_weight(intent: str | None, section: str | None, *, path: Path | str = DEFAULT_PATH) -> float:
    """1.0 (no-op) whenever `section` is falsy, the config file is missing, or neither the
    `global` block nor the `intent` block mentions this section."""
    if not section:
        return 1.0
    cfg = _load(str(path))
    weight = 1.0
    global_weights = cfg.get("global") or {}
    if section in global_weights:
        weight *= float(global_weights[section])
    if intent:
        intent_weights = cfg.get(intent) or {}
        if section in intent_weights:
            weight *= float(intent_weights[section])
    return weight
