"""Verification Layer (§25): re-check the answer's claims, numbers, calculations and
citations against the Evidence Workspace before the response is returned. See
docs/file-guide.md."""
from __future__ import annotations

from .models import ClaimCheck, VerificationReport
from .verifier import Verifier

__all__ = ["Verifier", "ClaimCheck", "VerificationReport"]
