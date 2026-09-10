"""Coverage / balance audit for a built FinQA-India set. See docs/file-guide.md."""
from __future__ import annotations

from typing import Any

# roadmap §38 target mix (per 850)
QUOTAS = {
    "factual": 100, "numerical": 100, "comparison": 100, "multi_step": 100,
    "why": 100, "how": 100, "causal": 100,
    "cross_document": 50, "analytical": 50, "adversarial": 50,
}
TOTAL = sum(QUOTAS.values())


def scaled_quotas(target: int) -> dict[str, int]:
    f = target / TOTAL
    return {k: max(1, round(v * f)) for k, v in QUOTAS.items()}


def audit(records: list[dict[str, Any]], *, target: int = TOTAL) -> dict[str, Any]:
    want = scaled_quotas(target)
    by_cat: dict[str, int] = {}
    companies: set[str] = set()
    numeric = numeric_with_gold = text = abstain = intent_pinned = 0
    for r in records:
        by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        companies.update(r.get("companies") or [])
        if r.get("answer_type") == "numeric":
            numeric += 1
            if r.get("reference_value") is not None:
                numeric_with_gold += 1
        elif r.get("answer_type") == "abstain":
            abstain += 1
        else:
            text += 1
        if r.get("expected_intent"):
            intent_pinned += 1
    gaps = {c: want[c] - by_cat.get(c, 0) for c in want if by_cat.get(c, 0) < want[c]}
    return {
        "n": len(records),
        "target": target,
        "by_category": dict(sorted(by_cat.items())),
        "quota_gaps": gaps,
        "quota_met": not gaps,
        "distinct_companies": len(companies),
        "numeric": numeric,
        "numeric_gold_coverage": round(numeric_with_gold / numeric, 4) if numeric else None,
        "text": text,
        "abstain": abstain,
        "intent_pinned": intent_pinned,
        "dup_questions": len(records) - len({r["question"].strip().lower() for r in records}),
    }


def format_audit(a: dict[str, Any]) -> str:
    lines = [
        f"records            : {a['n']}  (target {a['target']})",
        f"distinct companies : {a['distinct_companies']}",
        f"numeric / gold     : {a['numeric']} / {a['numeric_gold_coverage']}",
        f"text / abstain     : {a['text']} / {a['abstain']}",
        f"intent pinned      : {a['intent_pinned']}",
        f"dup questions      : {a['dup_questions']}",
        "by category:",
    ]
    for c, n in a["by_category"].items():
        flag = f"  (short {a['quota_gaps'][c]})" if c in a["quota_gaps"] else ""
        lines.append(f"  {c:<16}{n}{flag}")
    lines.append("quota met" if a["quota_met"] else f"quota gaps: {a['quota_gaps']}")
    return "\n".join(lines)
