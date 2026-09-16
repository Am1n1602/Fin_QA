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


def list_weighted_sections(intent: str | None, *, min_weight: float = 1.0,
                           path: Path | str = DEFAULT_PATH) -> list[str]:
    """§10 section hints: the sections this intent's config boosts above `min_weight`,
    read from the SAME YAML as `get_weight()` so hints and weights never disagree with
    each other. `[]` for an unconfigured/falsy intent -- callers should treat that as
    "no hint available", not "restrict to nothing"."""
    if not intent:
        return []
    cfg = _load(str(path))
    intent_weights = cfg.get(intent) or {}
    return sorted(s for s, w in intent_weights.items() if float(w) > min_weight)


def get_topic_weight(intent: str | None, topic: str | None, *, path: Path | str = DEFAULT_PATH) -> float:
    """Same shape as `get_weight()` but keyed by chunk `topic` (e.g. 'table') under its own
    `topics:` namespace in the YAML, so it never collides with the section weights above.
    1.0 (no-op) whenever `topic` is falsy or unconfigured."""
    if not topic:
        return 1.0
    cfg = _load(str(path))
    topics_cfg = cfg.get("topics") or {}
    weight = 1.0
    global_weights = topics_cfg.get("global") or {}
    if topic in global_weights:
        weight *= float(global_weights[topic])
    if intent:
        intent_weights = topics_cfg.get(intent) or {}
        if topic in intent_weights:
            weight *= float(intent_weights[topic])
    return weight
