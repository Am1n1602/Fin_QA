"""§23 final step: combine the structured checks and the document corroboration into
one ClaimStatus + a confidence + honest limitations.
"""
from __future__ import annotations

from finqa_v2.evidence import ClaimStatus

_BASE_CONF = {
    ClaimStatus.SUPPORTED: 0.85,
    ClaimStatus.PARTIALLY_SUPPORTED: 0.55,
    ClaimStatus.NOT_SUPPORTED: 0.30,
    ClaimStatus.INSUFFICIENT_EVIDENCE: 0.15,
}


def adjudicate(claim, checks, doc_status):
    """-> (ClaimStatus, confidence, [limitation, ...])."""
    verdicts = [c.verdict for c in checks]
    has_contra = "contradicts" in verdicts
    has_agree = "agrees" in verdicts
    mechanism_unprovable = any(c.name == "mechanism" and c.verdict == "no_data" for c in checks)
    only_no_data = verdicts and all(v in ("no_data", "unrelated") for v in verdicts)

    if has_contra and not has_agree:
        status = ClaimStatus.NOT_SUPPORTED
    elif has_contra and has_agree:
        status = ClaimStatus.PARTIALLY_SUPPORTED           # mixed signals
    elif has_agree and doc_status == "stated":
        status = ClaimStatus.SUPPORTED
    elif has_agree:
        status = ClaimStatus.PARTIALLY_SUPPORTED
    elif doc_status == "contradicted":
        status = ClaimStatus.NOT_SUPPORTED
    elif doc_status == "stated" and (mechanism_unprovable or only_no_data):
        status = ClaimStatus.PARTIALLY_SUPPORTED           # management asserts it; numbers are silent
    elif doc_status == "stated":
        status = ClaimStatus.PARTIALLY_SUPPORTED
    else:
        status = ClaimStatus.INSUFFICIENT_EVIDENCE

    conf = _BASE_CONF[status]
    if mechanism_unprovable:
        conf = max(0.1, conf - 0.1)
    if has_agree and doc_status == "stated":
        conf = min(0.95, conf + 0.05)

    lims: list[str] = []
    if mechanism_unprovable and claim is not None:
        lims.append(f"The '{claim.mechanism}' mechanism cannot be checked against structured "
                    f"data (no volume / pricing / demand series); the assessment rests on the "
                    f"reported aggregates and management commentary.")
    if doc_status == "absent":
        lims.append("No filing passage stating this management claim was retrieved.")
    if has_contra and has_agree:
        lims.append("Structured checks disagree with each other; treat the verdict as provisional.")
    return status, round(conf, 4), lims
