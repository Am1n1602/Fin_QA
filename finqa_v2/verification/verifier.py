"""Verifier (§25): runs the checks over a §31 response, then removes / marks-uncertain /
abstains per the roadmap. Mutates the response dict in place (claim statuses, limitations,
possibly the answer + confidence) and returns a VerificationReport.
"""
from __future__ import annotations

from finqa_v2.verification.checks import check_answer_numbers, check_calculation, check_claim
from finqa_v2.verification.models import ClaimCheck, VerificationReport

_ABSTAIN_PREFIX = ("[unverified] The figures in this answer could not be reconciled with the "
                   "underlying evidence. ")


class Verifier:
    def __init__(self, *, abstain_fraction: float = 0.5, soft_conf_cap: float = 0.6,
                 abstain_conf_cap: float = 0.3):
        self._abstain_fraction = abstain_fraction
        self._soft_cap = soft_conf_cap
        self._abstain_cap = abstain_conf_cap

    # ------------------------------------------------------------------ #
    def verify(self, response: dict, workspace, *, graph=None,
               check_numbers: bool = True) -> VerificationReport:
        """`check_numbers=False` for answers whose prose is verdict text with derived
        figures (Phase 11/12) rather than verbatim restatements of workspace values.
        `graph` (a ClaimGraph): status/confidence downgrades are mirrored onto its
        `Claim` objects so a ClaimGraphView built afterwards reflects verification."""
        checks: list[ClaimCheck] = []
        by_id = {e["evidence_id"]: e for e in response.get("evidence", [])}

        for calc in response.get("calculations", []):
            checks.append(check_calculation(calc))
        for claim in response.get("claims", []):
            checks.extend(check_claim(claim, by_id))
        if check_numbers:
            checks.extend(check_answer_numbers(response.get("answer", ""), workspace))

        return self._adjudicate(response, checks, graph)

    # ------------------------------------------------------------------ #
    def _adjudicate(self, response: dict, checks: list[ClaimCheck], graph=None) -> VerificationReport:
        adjustments: list[str] = []
        limitations = list(response.get("limitations", []))

        # 1. claims that failed a hard check -> not_supported
        failed_claims = {c.target.split(":", 1)[1] for c in checks
                         if c.hard_fail and c.target.startswith("claim:")}
        graph_claims = {c.claim_id: c for c in graph.claims} if graph is not None else {}
        for cl in response.get("claims", []):
            if cl.get("claim_id") in failed_claims:
                if cl.get("status") != "not_supported":
                    cl["status"] = "not_supported"
                    cl["confidence"] = round(float(cl.get("confidence", 0.0)) * 0.3, 4)
                    adjustments.append(f"claim marked not_supported: {cl.get('text', '')[:80]}")
                gc = graph_claims.get(cl.get("claim_id"))
                if gc is not None:
                    from finqa_v2.evidence.models import ClaimStatus

                    gc.status = ClaimStatus.NOT_SUPPORTED
                    gc.confidence = cl["confidence"]

        # 2. calculations that don't reproduce -> limitation
        for c in checks:
            if c.kind == "calculation" and c.verdict == "does_not_recompute":
                limitations.append(f"Calculation not reproduced on re-check: {c.detail}")
                adjustments.append(f"calculation flagged: {c.detail}")

        # 3. figures in the answer that disagree with the evidence
        numeric = [c for c in checks if c.kind == "numeric" and c.verdict in ("confirmed", "mismatch")]
        mism = [c for c in numeric if c.verdict == "mismatch"]
        confirmed = [c for c in numeric if c.verdict == "confirmed"]
        for c in mism:
            limitations.append(f"Unverified figure — {c.detail}")
        # abstain only when the figures are wrong as a body, not on a lone parse artifact
        abstain = (len(mism) >= 2 and not confirmed) or \
                  (bool(mism) and len(mism) / max(1, len(numeric)) >= self._abstain_fraction
                   and len(mism) > len(confirmed))

        # 4. citation weaknesses -> limitation only
        for c in checks:
            if c.verdict == "citation_weak":
                limitations.append(f"Weak citation: {c.detail}")

        # 5. apply the confidence / answer consequences
        conf = float(response.get("confidence", 0.0))
        if abstain:
            if not response.get("answer", "").startswith("[unverified]"):
                response["answer"] = _ABSTAIN_PREFIX + response.get("answer", "")
            conf = min(conf, self._abstain_cap)
            adjustments.append("answer marked [unverified]: numeric checks did not reconcile")
        elif failed_claims or any(c.kind == "calculation" and c.verdict == "does_not_recompute"
                                  for c in checks) or mism:
            conf = min(conf, self._soft_cap)

        response["confidence"] = round(conf, 4)
        response["limitations"] = list(dict.fromkeys(limitations))
        return VerificationReport(checks=checks, abstained=abstain, adjustments=adjustments)
