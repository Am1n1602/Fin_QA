# evaluation/baselines/ — Phase 21 baseline experiments (§40)

Before claiming the full architecture is better, compare it against three deliberately
simpler pipelines on the same question sample:

- **A — LLM only**: `Question -> LLM -> Answer`. No tools at all — whatever the model
  already knows.
- **B — Vector RAG**: `Question -> Vector Search -> LLM`. Dense retrieval only, no
  Financial Engine, no calculator, no verification.
- **C — Financial Engine + LLM**: `Question -> Financial Engine -> LLM`. The right
  number(s), handed to a prompting LLM with no documents and no verification.
- **D — Full Fin_QA**: the real `ReasoningOrchestrator` (planner + engine + hybrid RAG +
  calculator + reasoning + verification), unchanged.

A/B/C are intentionally minimal — no evidence workspace beyond what each name implies, no
citations engine, no verifier — so the comparison isolates what the full architecture adds.
All four are scored with the identical Phase-18 evaluators.

```bash
python -m evaluation.baselines.runner --dataset evaluation/datasets/finqa_india.jsonl \
    --sample 15 --sample-seed 13 --llm
```

**Budget**: each question costs ~1 LLM request for A/B/C and ~2 for D (planner + synth).
A 15-question sample is ~75 requests — keep `--sample` around 10–15 so one run fits the
60-request/process guard; `--baselines A_llm_only,C_engine_llm` narrows to a subset.
Deterministic (no `--llm`) is a no-op for A/B/C (they need the model) and the existing
Phase 18/20 floor for D.
