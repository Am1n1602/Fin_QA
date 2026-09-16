"""Strip server-side internals from any response before it leaves the API. See docs/file-guide.md.

Flagged since Phase 7: `Citation.uri` holds the server-side PDF path (`sources.uri`) --
harmless internally (the reasoning/verification layers use it), but it must never reach a
public client. Applied generically (recursive key removal) rather than per-endpoint,
because a `uri` can surface nested inside evidence/citation/claim-graph payloads from
*any* tool or the reasoning orchestrator, not just an obvious "sources" field.
"""
from __future__ import annotations

from typing import Any

_STRIP_KEYS = {"uri"}


def strip_server_paths(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_server_paths(v) for k, v in obj.items() if k not in _STRIP_KEYS}
    if isinstance(obj, list):
        return [strip_server_paths(v) for v in obj]
    if isinstance(obj, tuple):
        return [strip_server_paths(v) for v in obj]
    return obj
