# Fin·QA

**[Live demo](https://am1n1602.me/finqa-v2)** — the full 50-company dataset, hybrid
(lexical + dense) retrieval, LLM synthesis on by default. Runs on Google Cloud Run +
Firebase Hosting, both scaled to zero: the first visit after any idle period waits
roughly two minutes (~107s measured) while the full 261k-chunk corpus loads into a fresh
container; the page shows a wait screen until the API answers — an accepted
latency/cost trade-off, not a bug (detail in
[`deployment/README.md`](deployment/README.md#public-demo-google-cloud-run--firebase-hosting)).
This is a **frozen, manually-built snapshot**, not something that auto-updates with this
repo — same section has the rebuild/redeploy steps. A smaller, free-tier fallback (5
companies, lexical-only, on Render) also exists at
[`deployment/README.md`](deployment/README.md#public-demo-render).

Financial research API and dashboard for the NIFTY 50 universe. Ask it things like *"What
was TCS's ROE?"*, *"Compare RELIANCE and ONGC on leverage"*, or *"Why did HCLTECH's
profitability decline?"* and it answers with the calculation behind every number and the
filing passage behind every claim.

The core design constraint: an LLM never computes or invents a figure. All arithmetic
happens in a plain deterministic Python engine over normalized XBRL data; the LLM's only
job is to read the numbers and documents that engine and retrieval layer already produced
and write them up, citing which evidence each sentence came from. A separate verification
pass then independently checks the arithmetic and every citation before the answer goes
out, downgrading or abstaining on anything it can't confirm. Every code path also has a
no-LLM fallback, so the system still answers — more plainly — with zero model calls and $0
spend.

[**MANUAL.md**](MANUAL.md) has the full technical reference: every module, every config
variable, the API and metrics reference, deployment, and known limitations. This README is
the short version.

> **Two systems live in this repo.** Everything from here on — the architecture, the
> features, `finqa_v2/` + `dashboard_v2/` — describes the one that's live. An earlier
> iteration is kept untouched under `archive/` as a runnable reference, not part of what's
> running or described below; see [Project layout](#project-layout) for what's in it.

## Architecture

```
BSE/NSE XBRL filings + results PDFs + investor transcripts/presentations
        │
        ▼
XBRL normalization ──────────► SQLite (dev) or PostgreSQL + pgvector (prod)
        │                              │
        ▼                              │
Deterministic Financial Engine ◄───────┘
(ratios · growth/CAGR · valuation · segments · DuPont decomposition)
        │
        ├──► PDF → structure-aware chunks → BM25 + dense embeddings
        │         → hybrid retrieval (+ optional reranking)
        ▼
Query Planner (rules-based, LLM-assisted when a key is configured)
        ▼
Tool Registry — 15 typed functions; the only path any answer touches data or documents
        ▼
Reasoning Orchestrator
        ├── causal "why" questions       → hypothesis decomposition + structural testing
        ├── "is management's claim true" → cross-validation against reported figures
        └── everything else              → evidence assembly + LLM (or deterministic) synthesis
        ▼
Verification — independently checks calculations and citations, abstains on mismatch
        ▼
FastAPI ──► React/Vite dashboard (chat + per-company drill-down, claim-level evidence)
```

## What it does

- **Deterministic financial engine.** 17 ratios (ROE, ROCE, margins, leverage, coverage,
  liquidity), valuation multiples, YoY/QoQ growth, CAGR, segment attribution, and a
  DuPont/net-margin decomposition, each traceable to the exact source facts and formula
  used. A metric that can't be computed cleanly comes back `null` with a stated reason —
  never zero, never an approximation. Banks and insurers get their own handling (e.g.
  `total_income` in place of `revenue`) instead of being silently misreported.
- **Document retrieval with real citations.** Filing PDFs, investor decks, and
  earnings-call transcripts are chunked with page/section provenance and indexed both
  lexically (BM25) and semantically, so a "why" answer can point to the actual paragraph
  it came from.
- **Causal analysis that checks itself.** A "why did profitability decline" question
  decomposes the metric into candidate drivers (cost lines, segment mix, DuPont factors)
  and structurally tests each one against the numbers before calling anything supported.
- **Claim cross-validation.** "Management said growth was driven by BFSI — is that true?"
  is checked against both the segment data and the filing text, landing on `supported` /
  `partially_supported` / `not_supported` / `insufficient_evidence`.
- **Post-hoc verification.** Before an answer ships, the verifier independently attempts
  to recompute every calculation (a formula whose inputs aren't all pinned values is
  flagged `not_recomputable` rather than silently trusted) and reconciles every number in
  the prose against its source evidence; a claim that fails is downgraded, and an answer
  that fails as a whole is abstained rather than shown. Measured on the current
  51-question regression set below: 100% of cited claims are fully grounded (every
  evidence id resolves to real, unflagged evidence).
- **REST API and dashboard**, both pure transport over the same engine — neither computes
  anything on its own. The dashboard (`dashboard_v2/`) uses a sidebar layout and a
  navy-and-gold "ledger" theme, with light/dark modes and every claim rendered as an
  expandable evidence card.
- **Cost-aware LLM layer.** Groq's free tier by default (a 60-request/session, 180k
  token/day budget, enforced in code, not just documented), or an optional Anthropic path
  with a hard $3 spend cap that refuses a call rather than risk exceeding it.
- **500+ unit tests passing** (`python -m unittest discover -s finqa_v2`), plus the
  evaluation suite below, which runs against the live engine and retrieval stack rather
  than mocks.
- **An 850-question internal benchmark** across factual, numerical, comparison, causal,
  cross-validation, and adversarial categories, all 50 NIFTY 50 companies — see
  [Evaluation](#evaluation) for what running it actually shows, including where the
  numbers are weaker.

## Project layout

```
finqa_v2/            The system described above.
├── engine/           Ratios, growth, valuation, segments, decomposition
├── normalize/        XBRL → canonical facts
├── documents/        PDF extraction, section detection, chunking
├── retrieval/        BM25 + embeddings + hybrid fusion + reranking
├── tools/            Typed Tool Registry — the sanctioned data/document access path
├── planner/          Query planning (rules + LLM)
├── reasoning/        Orchestrator, prompt construction, deterministic synthesis
├── hypothesis/       Causal "why" question workflow
├── crossval/         Management-claim verification workflow
├── evidence/         Evidence/Claim/Calculation models and the Claim Graph
├── verification/     Recomputation and citation checks
├── llm/              Provider abstraction (Groq, Anthropic), rate/cost budgets
├── sqlite/, postgres/  Interchangeable repository implementations
├── dataset/          One-command rebuild + coverage audit
└── api/              FastAPI app

dashboard_v2/         React (Vite) frontend
evaluation/           Internal benchmark, evaluators, baseline comparisons
deployment/           Docker Compose stack, plus the Render and Cloud Run/Firebase
                      public-demo deploy targets

archive/              NOT LIVE — an earlier iteration (data_analysis/, rag/, qa_router/,
                      llm_router/, orchestrator/, fin_llm_platform/, its own api/ and
                      dashboard/), kept untouched as a runnable reference rather than
                      deleted. Nothing above depends on it or modifies it.
```

`finqa_v2/` and `archive/` share only the raw XBRL/PDF inputs under
`data_extraction/data/` and `database/data/` — `finqa_v2` writes its own `finqa_v2.db`,
separate from `archive`'s `financial_intelligence.db`. See
[`MANUAL.md §2`](MANUAL.md#2-repository-layout) for the full per-file breakdown.

## Design principles

- The LLM never computes or invents a number — every figure traces to the engine or a
  retrieved passage.
- A metric that isn't cleanly available returns `null` with a reason, never zero and never
  a substitute.
- Every claim carries its own evidence chain, down to a specific evidence id.
- Verification runs independently after synthesis and doesn't trust the writer's
  arithmetic or citations.
- Consolidated and standalone financials are never silently swapped for each other — a
  company that files only one basis shows the other as genuinely unavailable.
- Data-coverage gaps are stated plainly rather than papered over with the nearest
  available period.

## Getting started

### Prerequisites

- Python 3.11+ — needed at least once, to build the local dataset (`finqa_v2.db`).
- Node 18+, unless you're running everything through Docker Compose (see below), which
  also covers the API, PostgreSQL, and monitoring.
- A Groq API key (free) — the default LLM provider. An Anthropic key also works, with a
  configurable spend cap.
- Optional: a CUDA GPU for faster embedding/reranking during ingestion. The default
  install is CPU-only.

### Install

```bash
git clone https://github.com/Am1n1602/Fin_QA
cd Fin_QA

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -e .
# add the Anthropic path too:
pip install -e ".[anthropic]"
```

### Configure

```bash
cp .env.example .env
```

```
GROQ_API_KEY=your-key-here
ANTHROPIC_API_KEY=your-key-here   # optional
```

### Build the dataset and search indexes

```bash
python -m finqa_v2.dataset.build
python -m finqa_v2.retrieval.build_indexes
```

The first command imports company/index metadata, normalizes XBRL facts, extracts
segments, imports share prices, ingests filing PDFs into structured chunks, and runs a
coverage audit — each step is idempotent and resumable (`--from segments`, `--skip-docs`,
`--company TCS`). Run against the maintainer's own dataset, that audit currently reports
100/100 on all 50 NIFTY 50 companies (`python -m finqa_v2.dataset.audit`) — your own build
depends on what BSE/NSE currently serves, so re-run it yourself rather than assuming this
holds. The second command builds the BM25 and embedding indexes the retriever needs
(`--device cuda` if you have a GPU).

Prefer PostgreSQL? See [`deployment/README.md`](deployment/README.md) — the repository
interface is identical either way.

## Running it

### Everything via Docker Compose

```bash
cd deployment/compose
docker compose up -d --build postgres minio minio-init api dashboard prometheus grafana
```

| Service | URL | |
|---|---|---|
| Dashboard | http://localhost:5174 | |
| API | http://localhost:8010 (`/docs` for interactive schema) | |
| Prometheus | http://localhost:9090 | |
| Grafana | http://localhost:3000 | login with your own `GRAFANA_ADMIN_USER`/`PASSWORD` |

Grafana, Postgres, and MinIO have no default passwords — copy
`deployment/compose/.env.example` to `deployment/compose/.env` and set
`GRAFANA_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD` first, or `docker
compose up` refuses to start those services. See `deployment/README.md` for details.

One-time, once `postgres` is healthy, load your local dataset into it:

```bash
export FINQA_PG_URL=postgresql://finqa:<POSTGRES_PASSWORD>@localhost:55432/finqa
python -m finqa_v2.postgres.migrate
```

`GROQ_API_KEY`/`ANTHROPIC_API_KEY` are read from your shell or a `.env` file in
`deployment/compose/`. `docker compose down -v` also wipes the Postgres/MinIO volumes.
Full detail in [`deployment/README.md`](deployment/README.md) and
[`MANUAL.md`](MANUAL.md#14-deployment).

### Individually, without Docker

```bash
finqa-api-v2
# or: uvicorn finqa_v2.api.main:app --port 8010
```

```bash
cd dashboard_v2
npm install
npm run dev -- --port 5174
```

Set `VITE_API_BASE_URL` in `dashboard_v2/.env.local` if the API isn't on
`localhost:8010`. Configuration is otherwise environment-driven — see
[`MANUAL.md §21`](MANUAL.md#21-full-environment-variable-reference) for the full list, or
`finqa_v2/api/config.py` in source.

### Try it

- *"What was TCS's revenue in FY2026?"*
- *"What is RELIANCE's ROE?"*
- *"Compare TCS and Infosys on profitability."*
- *"Which segment contributed most to Reliance's revenue growth?"*
- *"Why did HCLTECH's profitability decline?"*
- *"TCS management said growth was driven by the BFSI segment — is that supported?"*

## Evaluation

```bash
python -m unittest discover -s evaluation

# deterministic scoring, zero LLM calls
python -m evaluation.runners.v2_runner --dataset evaluation/datasets/finqa_v2_eval.jsonl --no-retriever

# regenerate the 850-question internal benchmark
python -m evaluation.datasets.finqa_india.build

# compare the full pipeline against simpler baselines
python -m evaluation.baselines.runner --dataset evaluation/datasets/finqa_india.jsonl --sample 20 --llm
```

The benchmark (`evaluation/datasets/finqa_india.jsonl`, 850 questions) spans factual,
numerical, comparison, multi-step, causal, cross-document, analytical, and adversarial
questions across all 50 NIFTY 50 names, regenerated 2026-09-26 against the final
50-company corpus. The 850-question deterministic run below predates that regeneration
(2026-09-10, pre-restart data) and is due for a re-run — treat it as historical context,
not a current number. The regression/smoke set is current:

**51-question regression set, deterministic path (0 LLM calls), full production
retrieval index (BM25 + MiniLM embeddings, built on Kaggle GPU over the complete
261,479-chunk corpus), 2026-09-26:**

| Check | Result | n checked |
|---|---|---|
| Numerical accuracy | 100% | 23 |
| Claim groundedness (every cited evidence id is real) | 100% | 43 |
| Correct abstention (declines what it can't answer) | 98.0% | 51 |
| Overall correctness (keyword/tolerance match to reference) | 86.1% | 43 |

Retrieval, same index, company-filtered:

| Mode | Recall@5 | MRR | nDCG@10 |
|---|---|---|---|
| Lexical (BM25) | 68.2% | 0.536 | 0.557 |
| Vector (MiniLM) | 40.9% | 0.258 | 0.301 |
| Hybrid | 50.0% | 0.510 | 0.546 |

Lexical ties or beats vector/hybrid here — a real, repeated finding in this project (near-duplicate
boilerplate across quarterly filings dilutes embedding similarity more than it dilutes
BM25 term matches). A cross-encoder reranker measured a real win over this at pilot scale
(+0.13-0.18 Recall@5) but hasn't been re-validated at full scale and stays off by default.
Raw report: [`evaluation/regression/baselines/deterministic_v2.json`](evaluation/regression/baselines/deterministic_v2.json).

**Older, larger, pre-restart runs — kept only for the one finding that doesn't need
re-validating (the architecture, not the exact numbers), full tables in their raw
reports:**

- Full 850-question deterministic run (2026-09-10, predates the historical-depth
  restart): 100% numerical accuracy (n=200), 58.0% strict keyword/tolerance correctness
  (n=800) — correctness undercounts real quality here, since causal/adversarial answers
  rarely match one reference phrasing even when the numbers and evidence are right. Raw
  report: [`baseline_deterministic.json`](evaluation/datasets/finqa_india/baseline_deterministic.json).
- 204-question, four-pipeline comparison (Claude Sonnet, $3 cap, 2026-09-11): numerical
  accuracy was 0.0–4.2% for an LLM with no deterministic engine (raw model knowledge or
  vector RAG alone) versus 83–92% once the engine is in the loop, regardless of whether
  verification sits on top — the categorical case for this architecture, not a number
  expected to move. Raw report: [`baselines-claude-sonnet5.json`](evaluation/reports/baselines-claude-sonnet5.json).

A regression gate compares any new run against a pinned baseline and fails on a metric
regression beyond tolerance. See [`MANUAL.md §17`](MANUAL.md#17-evaluation-framework) for
the evaluator definitions, the regression harness, and baseline-comparison detail.

## Known limitations

- **Historical depth is real but uneven.** Most of the NIFTY 50 (48/50 companies) now
  has structured XBRL data back to FY2018-19 via NSE's older "Financial Results" API,
  not just the most recent filings. Two exceptions: HDFCLIFE and SBILIFE (insurers) only
  reach back to FY2025 — that NSE endpoint's own historical coverage for insurers is
  genuinely shallower, not a gap in this pipeline. JIOFIN only reaches FY2024, matching
  its real 2023 listing date. A question about a period before a company's own history
  gets an honest "not available," never an approximation.
- **Segment margin isn't shown**, only segment revenue — the filings disclose one, not
  the other, and nothing here approximates it.
- **The consolidated/standalone toggle is manual** — a company that files only one basis
  never has the other silently substituted in. Bank capital-adequacy/asset-quality ratios
  (CET1, Tier 1, gross/net NPA) are standalone-only by regulation — asking for them
  without saying "standalone" returns the (correctly) unavailable consolidated figure.
- **Running components individually defaults to SQLite**; PostgreSQL is fully supported
  but opt-in via one environment variable.

Full list, with the reasoning behind each, in [`MANUAL.md §18`](MANUAL.md#18-known-limitations).

## License

MIT — see [`LICENSE`](./LICENSE).
