"""Claim Graph view (§24): every important claim wired to the evidence, calculations,
sources and confidence breakdown that stand behind it -- the structure the Verifier
checks and the dashboard expands. See docs/file-guide.md.

The `ClaimGraph` object itself lives in `finqa_v2/evidence/graph.py` (Phase 7); this
package is the read/explain/export layer on top of it.
"""
from __future__ import annotations

from .view import ClaimGraphView

__all__ = ["ClaimGraphView"]
