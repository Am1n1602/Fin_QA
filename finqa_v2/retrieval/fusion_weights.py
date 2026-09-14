"""Per-intent RRF leg weight config (§16) -- loaded from YAML, never hardcoded in fusion
logic. See finqa_v2/retrieval/fusion_weights.yaml for the actual weights and
`HybridRetriever.retrieve(..., weighted_fusion=True)` for where they're applied."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("fusion_weights.yaml")


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def get_fusion_weights(intent: str | None, *, path: Path | str = DEFAULT_PATH) -> tuple[float, float]:
    """(lexical_weight, vector_weight) for this intent -- falls back to the `default:` block,
    then to (1.0, 1.0) plain RRF if even that is missing or the config file doesn't exist."""
    cfg = _load(str(path))
    entry = (intent and cfg.get(intent)) or cfg.get("default") or {}
    return float(entry.get("lexical", 1.0)), float(entry.get("vector", 1.0))
