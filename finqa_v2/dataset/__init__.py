"""Dataset management (§15/§42): coverage audit + a one-command rebuild of finqa_v2.db.
See docs/file-guide.md."""
from __future__ import annotations

from .audit import audit_coverage

__all__ = ["audit_coverage"]
