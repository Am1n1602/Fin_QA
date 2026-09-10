# Question-record schema (`*.jsonl`, one JSON object per line)

Designed to serve both the v1 baseline capture and v2 evaluation without a schema change.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Stable unique id, e.g. `num-001`. Never reused. |
| `category` | string | yes | One of §38: `factual`, `numerical`, `comparison`, `multi_step`, `why`, `how`, `causal`, `cross_document`, `analytical`, `adversarial`. |
| `question` | string | yes | The natural-language question, exactly as asked. |
| `companies` | string[] | yes | NSE tickers the question concerns (`[]` if none / universe-wide). |
| `period` | string \| null | yes | Target period label if any (`"FY2026"`, `"Q1FY2026"`), else `null`. Not parsed by the v1 classifier — informational. |
| `answer_type` | string | yes | `numeric` \| `text` \| `abstain`. `abstain` = the correct behavior is a controlled no-answer. |
| `expected_intent_v1` | string \| null | yes | Intent the v1 `classify.py` is expected to assign (`numeric_fact`, `trend`, `comparison`, `ranking`, `financial_health`, `report`, `narrative`, `regulatory_disclosure`, `complex`, `unknown`). `null` if not yet pinned. |
| `should_abstain` | bool | yes | True when the system should decline / say "no evidence" rather than answer. |
| `reference_answer` | string \| null | no | Gold free-text answer. `null` until Phase 20. |
| `reference_value` | number \| null | no | Gold numeric value (for `answer_type: numeric`). `null` until Phase 20. |
| `reference_unit` | string \| null | no | Unit for `reference_value` (`"INR crore"`, `"%"`, `"x"`). |
| `reference_sources` | object[] | no | Gold citations: `{document, page, section}`. `[]` until Phase 20. |
| `tolerance_pct` | number \| null | no | Allowed relative error for numeric scoring (default 1.0 when scoring is added). |
| `notes` | string | no | Rationale, gotchas, why it's adversarial, etc. |

## Conventions

- One universe: NIFTY 50 tickers only, real NSE symbols (`TCS`, `INFY`, `HDFCBANK`, …).
- `adversarial` items usually set `should_abstain: true` and `answer_type: "abstain"`
  (e.g. a year not in the corpus, a metric the pipeline can't produce).
- Banks/NBFC-framework and CET1/NPA-style questions are included on purpose — v1's
  documented behavior is to abstain / caveat, and v2 must not regress that into a
  confident wrong answer.
- Keep `id` prefixes aligned to `category` for grep-ability
  (`fact-`, `num-`, `cmp-`, `multi-`, `why-`, `how-`, `causal-`, `xdoc-`, `ana-`, `adv-`).
