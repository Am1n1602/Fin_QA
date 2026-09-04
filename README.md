# Financial Statement LLM — Indian Equities Intelligence Platform

A local-first pipeline that turns raw NSE/BSE regulatory filings into a natural‑language question‑answering system for Indian listed companies — e.g. *"What is TCS's ROE?"*, *"Compare AXISBANK and HDFCBANK on leverage"*, *"Why did HCLTECH's profitability decline?"*.

Every financial number comes from a **deterministic calculation engine**, never from an LLM. The LLM layer is only ever used to write up numbers that have already been computed and verified — and every LLM-written answer is mechanically checked against its source data before it's shown to you.

```
BSE / NSE filings (XBRL + PDF)
        │
        ▼
 XBRL parsing + normalization  ──────────►  SQLite database
        │                                        │
        ▼                                        │
 Deterministic Financial Engine  ◄────────────────┘
 (ratios · trends · peer comparison · ranking · Piotroski/Altman)
        │
        ├──────────────► PDF text → chunks → embeddings → FAISS index
        │                          (RAG: narrative / "why" answers)
        ▼
   QA Router (classifies each question, picks a path)
        │
        ├── numeric fact / trend / ranking / health  →  structured DB query (no LLM)
        └── narrative / complex synthesis            →  RAG + Hybrid LLM (Ollama local / Groq or Anthropic cloud)
        │
        ▼
  `finqa` CLI  →  grounded, source-checked answer
```

---

## What this is, concretely

- **Data**: pulls quarterly/annual XBRL filings and results PDFs directly from NSE/BSE for the NIFTY 50 universe (auto-refreshed, not a hand-maintained list).
- **Facts, not guesses**: XBRL tags are mapped to a canonical schema; anything that can't be cleanly mapped is left as `null` with a reason — never zero-filled or approximated.
- **Analysis**: a single Financial Engine computes every ratio, growth figure, peer percentile, fundamental ranking score, and financial-health score (Piotroski F-Score, partial Altman Z''). No other module recomputes these — they only consume the engine's output.
- **Document intelligence**: filing PDFs are chunked, embedded, indexed (FAISS), and retrieved with a hybrid search (semantic + BM25 + phrase overlap) and cross-encoder reranker, for the qualitative content XBRL can't capture (management commentary, litigation, deal narratives).
- **QA Router**: classifies each question and decides whether it needs a structured DB lookup, a RAG retrieval, or both plus an LLM to synthesize the final answer.
- **Hybrid LLM**: local Ollama handles cheap/simple tasks; a cloud model (Groq by default — free tier; Anthropic optional) handles complex reasoning and narrative writing. Every cloud-written numeric claim is automatically checked against the source figures/units before being returned.
- **Ships as a real CLI**: `pip install -e .` gives you `finqa` (ask questions), `finqa-pipeline` (refresh data), and `finqa-setup` (schedule automatic refreshes) as console commands, usable from anywhere.

---

## Project layout

The project is seven sibling folders plus one thin packaging layer, sharing a single Python virtual environment (**no per-folder venvs**):

| Folder | Responsibility |
|---|---|
| `data_extraction/` | Fetches NSE/BSE filings (XBRL + PDF) for the live NIFTY 50 universe; parses XBRL into canonical financial facts |
| `data_analysis/` | Financial Engine: ratios, valuation, historical trends, peer comparison, fundamental ranking, financial health (Piotroski/Altman), report aggregation |
| `database/` | Shared SQLite database (`financial_intelligence.db`) both of the above load into; query helpers for the rest of the system |
| `rag/` | Extracts text from filing PDFs, chunks it, embeds it, builds a FAISS index, retrieves and reranks passages |
| `qa_router/` | Classifies incoming questions and routes them to the right combination of structured query / RAG / LLM |
| `llm_router/` | The hybrid LLM layer — local Ollama client, cloud client (Groq / Anthropic), routing logic, prompt templates, verification checks |
| `orchestrator/` | Chains fetch → extract → analyze → load → RAG-ingest into one unattended, resumable pipeline run |
| `fin_llm_platform/` | Thin packaging shell installed by `pip install -e .` — wires the above into three console commands, nothing reimplemented |


---

## Build status

| Stage | What it delivers | Status |
|---|---|---|
| 0–1. Preserve & stabilize extraction pipeline | Reliable XBRL → canonical facts | ✅ |
| 2. Normalization + database | Shared SQLite store | ✅ |
| 3. Financial calculation engine | Deterministic ratios/valuation, single source of truth | ✅ |
| 4. Historical trends | QoQ/YoY growth, trend detection | ✅ |
| 5. Peer comparison | Cross-sectional comparison across a peer set | ✅ |
| 6. Fundamental ranking | Percentile-based composite scoring (QMJ-style) | ✅ |
| 7. Financial health | Piotroski F-Score (8/9 criteria), partial Altman Z'' | ✅ |
| 8. Automated research reports | Part A — structured JSON report aggregation | ✅ Part A · Part B (LLM narrative) folded into Stage 11 |
| 9. RAG | PDF ingestion, chunking, embeddings, dual FAISS index, hybrid retrieval + reranking | ✅ |
| 10. QA Router | Question classification → structured / RAG / LLM routing | ✅ |
| 11. Hybrid LLM | Ollama (local) + Groq/Anthropic (cloud) router, numeric & unit verification guardrails | ✅ |
| 12. Scale to NIFTY 50 + production CLI | Live universe sourcing, full pipeline orchestration, rate-limit sizing, performance validation at scale, CLI robustness, `pip install`-able package with scheduler | ✅ (all 6 phases, live-confirmed) |
| 13. API | REST API over financials/ratios/trends/ranking/health/QA | ⏳ not started — next up |
| 14. Dashboard | Web frontend | ⏳ not started |

Everything through Stage 12 has been validated against real filings and cross-checked against independent sources (Screener.in, Tickertape, GuruFocus, TipRanks, Value Research, and BSE's own results snapshots) — not just internal consistency checks.

---

## Core design principles

- **Deterministic financial layer.** Every ratio, growth figure, ranking, and health score is computed by plain Python, never by an LLM. The Financial Engine (`data_analysis/src/analysis/`) is the single source of truth — no other module recalculates a metric it already produces.
- **No silent approximation.** When a clean, unambiguous XBRL tag doesn't exist for something, that feature is excluded and documented as excluded — never zero-filled, never estimated with a proxy.
- **Consolidated is primary.** Standalone financials are kept as a diagnostic/secondary view only; several real distortions (e.g. one-off "other income" inflating standalone margins) confirmed this is the right default.
- **LLM as interpreter, not calculator.** The hybrid LLM layer only classifies, routes, summarizes, and writes up numbers the deterministic engine has already produced — and every LLM-produced numeric claim is automatically checked against its source before being shown.
- **RAG for narrative, structured queries for facts.** "What was TCS's ROE?" never touches the document index; "Why did HCLTECH's margin decline?" does. The QA router enforces this split.

**Known scope limits (current, not bugs):**
- The ranking/valuation/health framework (Capital Employed, Enterprise Value, current-liabilities-based safety checks) is built for non-financial companies. Banks/NBFCs need a different framework (e.g. CAMEL-style) and aren't meaningfully covered yet.
- Multi-year (5-year) history and CAGR-based metrics are limited by what NSE/BSE actually expose for older periods; Growth is intentionally left out of the ranking formula for this reason rather than approximated.
- The default install is CPU-only (`torch`/`faiss-cpu`); a CUDA GPU speeds up RAG ingestion if you install a CUDA build of `torch` yourself.

---

## Getting started

### Prerequisites

- **Python 3.11+**
- A **Groq API key** (free tier) — the default cloud LLM provider. An Anthropic API key works too if you'd rather use Claude for the cloud path.
- *Optional:* a local [Ollama](https://ollama.com) install for fully local LLM synthesis with no cloud calls — if it's not installed, the router falls back to the cloud provider automatically.
- *Optional:* a CUDA-capable GPU for faster RAG ingestion (embedding + reranking).

### Install

```bash
git clone https://github.com/Am1n1602/Local_LLM_Financial_Statement.git
cd Financial_Statement_LLM_NLP

python -m venv venv

# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -e .
# or, to also enable the Anthropic/Claude cloud path:
pip install -e ".[anthropic]"
```

This installs every dependency across all six sibling projects from a single root `pyproject.toml`, and registers three console commands: `finqa`, `finqa-pipeline`, `finqa-setup`. It's an **editable** install — the sibling project folders stay on disk exactly where they are; don't move `fin_llm_platform/` away from them after installing.

### Configure your LLM key

Copy the example config and set your API key as a real environment variable — never commit it:

```bash
cp llm_router/config/llm_config.example.yaml llm_router/config/llm_config.yaml
```

```bash
# .env or your shell's environment
GROQ_API_KEY=your-key-here
# optional, only if using the Anthropic path
ANTHROPIC_API_KEY=your-key-here
```

### Build the database and search index

```bash
finqa-pipeline
```

Runs, in order: refresh the NIFTY 50 constituent list → fetch filings for every company → extract XBRL facts → compute ratios/analysis → load into the database → ingest PDFs into the RAG index. A full 50-company run takes roughly an hour the first time (fetching is the slow part); re-running later only picks up new filings and index changes.

Useful flags: `finqa-pipeline --only fetch`, `finqa-pipeline --skip universe`, `finqa-pipeline --dry-run`.

---

## Usage

```bash
# one-off question
finqa "What is TCS's ROE?"

# interactive session — background workers stay warm across questions
finqa
> Compare AXISBANK and HDFCBANK on leverage
> Which companies have the best financial health?
> quit

# raw JSON output, for scripting
finqa "What is TCS's ROE?" --json
```

Question types that work today:

- **Direct numeric facts** — *"What was HDFCBANK's revenue last quarter?"*
- **Trends** — *"How has SBILIFE's ROE trended over the last few years?"*
- **Comparisons** — *"Compare BAJFINANCE and BAJAJFINSV on leverage"*
- **Rankings** — *"Which companies have the best financial health?"*
- **Full company reports** — financial health / ranking / valuation summary for a single company
- **Narrative "why" questions**, answered from the actual filing text — *"Why did HCLTECH's profitability decline?"*

Use each company's real NSE ticker (e.g. `BAJAJFINSV`) — name matching is alias-based.

### Scheduling automatic refreshes

```bash
finqa-setup --interval daily              # default 03:00 local time
finqa-setup --interval weekly --time 02:30
finqa-setup --interval monthly

finqa-setup --status
finqa-setup --remove
```

Registers a real OS-level job (crontab on Linux/macOS, Task Scheduler on Windows) that runs the full pipeline on your chosen interval.

---

## Data & validation

Originally built and cross-validated against six IT-services companies — **TCS, INFY, HCLTECH, WIPRO, TECHM, LTM— then scaled to the full, live-refreshed **NIFTY 50** universe in Stage 12. Companies that drop out of the index on reconstitution are marked inactive, not deleted; their historical data stays queryable.

Every layer has been checked against independent sources, not just internal consistency — e.g. TCS's computed TTM EPS, P/E, current ratio, and P/B all matched (within a normal range) figures independently reported by   TipRanks,Value Research, and Tickertape for the same periods.

---

## Roadmap — what's next

- **Stage 13 — API**: expose financials, ratios, trends, ranking, peer comparison, health, and QA over REST.
- **Stage 14 — Dashboard**: a web frontend once the API is stable.
- Open, non-blocking items: a Banks/NBFC-appropriate health framework, deeper multi-year history (blocked on filing availability, not on this codebase), and root-causing occasional cloud-LLM latency variance on complex questions.

---

## License
