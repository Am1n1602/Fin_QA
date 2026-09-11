# Fin·QA — Evidence-Grounded Financial Intelligence for Indian Equities

A financial research system for the NIFTY 50 universe that answers questions like *"What was TCS's ROE?"*, *"Compare RELIANCE and ONGC on leverage"*, *"Why did HCLTECH's profitability decline?"*, or *"Management said growth was driven by BFSI — is that supported?"* — and shows exactly which numbers, calculations, and filing passages back every claim in the answer.

Every financial figure comes from a **deterministic calculation engine**, never from an LLM guessing or computing on the fly. The LLM only ever writes up numbers and facts that have already been computed, retrieved, and packaged into an evidence workspace — and a separate verification pass then re-checks the written answer against that same evidence before it's shown to you.

```
BSE/NSE XBRL filings + results PDFs, investor transcripts, presentations
        │
        ▼
 XBRL normalization ──────► SQLite (or PostgreSQL + pgvector)
        │                          │
        ▼                          │
 Deterministic Financial Engine ◄──┘
 (metrics · ratios · growth · CAGR · valuation · segments · DuPont decomposition)
        │
        ├───────► PDF text → structure-aware chunks → BM25 + dense embeddings
        │                    → hybrid retrieval + reranking (management commentary,
        │                       earnings-call transcripts, risk factors, segment notes)
        ▼
   Query Planner  (rules-based, or an LLM planner when available)
        │
        ▼
   Tool Registry  (~15 typed tools — the ONLY way any answer touches data or documents)
        │
        ▼
   Reasoning Orchestrator
        ├── causal "why" questions      → hypothesis generation + structural testing
        ├── "is management's claim true"→ cross-validation against the reported numbers
        └── everything else             → an Evidence Workspace assembled from tool output
        │
        ▼
   Answer synthesis (LLM, or a deterministic no-LLM fallback) → Claim Graph
        │
        ▼
   Verification  (recomputes every calculation, checks every citation, flags or
                  abstains on anything that doesn't reconcile with its own evidence)
        │
        ▼
  A grounded answer: Answer → Key findings → Supporting numbers → Evidence → Sources
        │
        ├──────► FastAPI REST layer — every read path above, computes nothing itself
        └──────► React/Vite dashboard — Home, Companies, Company details, Rankings,
                 Research briefs, and a Financial QA chat with per-claim drill-down
```

---

## What this actually does today

- **A real Financial Engine**, not a spreadsheet-in-code: 17 ratios (ROE, ROCE, margins, leverage, coverage, liquidity), valuation multiples (P/E, P/B, EV/EBITDA, yields), YoY/QoQ growth and CAGR, cross-company ranking, per-segment revenue and growth-attribution, and a DuPont/net-margin decomposition — all traceable back to the exact input facts and formula used. A metric that can't be computed cleanly comes back as "not available" with a stated reason, never a zero or an approximation. Banks and insurers get their own handling (e.g. `total_income` in place of `revenue`, standalone-basis-only filers) rather than being silently misreported.
- **Document intelligence with real citations**: filing PDFs, investor presentations, and earnings-call transcripts are split into structure-aware chunks (with section/page provenance), indexed both lexically (BM25) and semantically (dense embeddings), retrieved through a hybrid search, and reranked — so a "why did X happen" answer can point to the actual paragraph it came from, not a vague summary.
- **An LLM that can't invent numbers.** The reasoning layer hands the LLM a fixed set of already-computed facts and retrieved passages (the "Evidence Workspace") and instructs it to write from that evidence only, citing an evidence ID for every claim. A no-LLM deterministic fallback exists for every question type, so the system still answers (more plainly) with zero LLM calls.
- **Causal reasoning that tests itself.** A "why did profitability decline" question doesn't just retrieve a plausible-sounding paragraph — it decomposes the metric into candidate drivers (margin bridge, segment mix, cost lines, DuPont factors), generates hypotheses, and structurally checks each one against the actual numbers before ever calling it "supported."
- **Cross-validation against management's own claims.** "Management said growth was driven by BFSI — is that true?" extracts the claim, checks it against the segment/growth data, and separately checks whether the filings actually say so — landing on `supported` / `partially supported` / `not supported` / `insufficient evidence`, never a shrug.
- **A verification pass that recomputes, not just re-reads.** Before an answer reaches you, every calculation is independently recomputed from its pinned inputs, every citation is checked against the evidence it claims to cite, and every number stated in the answer's prose is reconciled against the underlying figures — a claim that fails is downgraded or the whole answer is abstained, with the reason shown.
- **Claim-level drill-down, all the way through.** Every answer decomposes into individual claims; each claim expands to show its supporting numbers, the calculation that produced them (with inputs and formula), the exact filing passages behind it (with page and section), and deduplicated sources — in both the API response and the dashboard UI.
- **A REST API and a web dashboard**, both computation-free transport layers over the same engine: the API exposes every read path (companies, financials, ratios, growth, segments, rankings, search, research briefs, and free-form QA); the dashboard is a full evidence-grounded frontend over it, including a manual consolidated/standalone basis toggle for companies (like insurers) that only file one or the other.
- **A cost-aware LLM layer.** Works with a free-tier Groq model out of the box, or a paid Anthropic (Claude) model with a hard dollar spend cap that reserves cost before every call and never lets a run silently overspend.
- **An honest, internal evaluation framework**, not just vibes: a purpose-built 850-question benchmark across factual/numerical/comparison/trend/causal/cross-validation/adversarial categories, scored on numerical accuracy, groundedness, citation precision/recall, abstention accuracy, and unsupported-claim rate — plus a controlled comparison against three deliberately simpler pipelines (LLM-only, retrieval-only, engine-without-verification) that shows numeric accuracy goes from 0% to 100% the moment the deterministic engine is in the loop, and that the full pipeline's groundedness (every claim traces to real evidence) is categorically different from the simpler baselines, which have no such structure at all.

---

## Project layout

```
finqa_v2/            The current system — the folder everything above describes.
├── engine/           Financial Engine: metrics, ratios, growth, valuation, segments, decomposition
├── normalize/        XBRL → canonical facts, period resolution, unit handling
├── documents/        PDF extraction, section detection, structure-aware chunking
├── retrieval/        BM25 + dense embeddings + hybrid fusion + reranking
├── tools/            The typed Tool Registry — the only sanctioned data/document access path
├── planner/          Rules-based and LLM query planners
├── reasoning/         The Reasoning Orchestrator, LLM prompt + deterministic synthesis
├── hypothesis/       Causal "why" question workflow (decomposition + structural testing)
├── crossval/         "Is management's claim supported?" workflow
├── evidence/         Evidence / Claim / Calculation models and the adapters that build them
├── claimgraph/       Per-claim provenance explain/export layer
├── verification/     Recomputation, citation, and support checks; abstention logic
├── llm/              LLM provider abstraction (Groq, Anthropic), rate/cost budgets
├── sqlite/, postgres/  Two interchangeable repository implementations (same interface)
├── prices/           EOD share-price import (for valuation ratios)
├── dataset/          One-command dataset rebuild + coverage audit
├── scale/            Footprint measurement and scale projection
└── api/              FastAPI app — one router per resource, computes nothing itself

dashboard_v2/         React (Vite) dashboard over the API above.
evaluation/           The internal benchmark, evaluators, baseline comparison, regression gate.
deployment/           PostgreSQL + pgvector compose setup (an alternative to SQLite).
```

A separate, earlier iteration of this project — `data_analysis/`, `rag/`, `qa_router/`, `llm_router/`, `orchestrator/`, `fin_llm_platform/`, and its own `api/`/`dashboard/` — was the first working version and is kept as a stable, still-runnable reference point under `archive/`, rather than deleted (its console commands, `finqa`/`finqa-pipeline`/`finqa-setup`/`finqa-api`, still work from there). The `data_extraction/data/` and `database/data/` folders it also used are the two exceptions: they stayed at the repo root because `finqa_v2/`'s own dataset-rebuild pipeline reads from them directly. `finqa_v2/` and `dashboard_v2/` are additive: nothing above is a rewrite *of* that earlier code, and nothing in this project modifies it.

---

## Core design principles

- **The LLM never computes or invents a number.** Every figure in an answer traces back to the Financial Engine or a retrieved document passage, never to LLM arithmetic or LLM knowledge.
- **No silent approximation.** A metric that isn't cleanly available comes back as `null` with a stated reason — never zero-filled, never estimated as a proxy for something else.
- **Every claim carries its own evidence.** The Evidence Workspace → Claim Graph pipeline exists so that "why does the system believe this" always has a concrete, inspectable answer — down to the exact evidence ID.
- **Verification happens after synthesis, independently.** The verifier doesn't trust the LLM's arithmetic or citations — it redoes the calculation and re-checks the citation itself, and downgrades or abstains when something doesn't hold up.
- **Consolidated vs. standalone is a real distinction, never silently substituted.** A company that only files standalone (most insurers) shows genuinely unavailable data under "consolidated" rather than having one basis quietly stand in for the other — the dashboard exposes a manual toggle instead.
- **Honesty about data coverage.** If the data doesn't reach back to a period a question asks about, the system says so plainly rather than answering with whatever period it does have.

---

## Getting started

### Prerequisites

- **Python 3.11+** and **Node 18+** (for the dashboard)
- A **Groq API key** (free tier) — the default LLM provider. An **Anthropic API key** works too, with a configurable hard spend cap.
- *Optional:* a CUDA GPU for faster embedding/reranking during document ingestion; the default install is CPU-only.
- *Optional:* Docker, if you want to run against PostgreSQL + pgvector instead of the default SQLite file.

### Install

```bash
git clone https://github.com/Am1n1602/Fin_QA
cd Fin_QA

python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -e .
# or, to also enable the Anthropic/Claude cloud path:
pip install -e ".[anthropic]"
```

### Configure your LLM key

```bash
cp .env.example .env
```

```bash
# .env
GROQ_API_KEY=your-key-here
# optional, only if you want the Anthropic path
ANTHROPIC_API_KEY=your-key-here
```

### Build the database, document index, and search index

```bash
python -m finqa_v2.dataset.build
python -m finqa_v2.retrieval.build_indexes
```

The first command imports company/index metadata, normalizes XBRL facts, extracts reportable segments, imports share prices, ingests filing PDFs into structured chunks, and runs a coverage audit — each step is idempotent and resumable (`--from segments`, `--skip-docs`, `--company TCS`). The second builds the BM25 and dense-embedding indexes the hybrid retriever needs (`--device cuda` if you have a GPU).

*Prefer PostgreSQL?* See `deployment/README.md` — the repository interface is identical either way, so nothing above the database layer changes.

---

## Running it

### API

```bash
finqa-api-v2
# or: uvicorn finqa_v2.api.main:app --port 8010
```

Interactive docs at `/docs`. Key endpoints:

- `GET /api/v2/companies`, `/companies/{ticker}`, `/companies/{ticker}/peers`
- `GET /api/v2/companies/{ticker}/financials`, `/ratios`, `/ratios/decompose`, `/growth`, `/growth/cagr`, `/segments`, `/segments/growth`
- `GET /api/v2/rankings`, `/search`, `/companies/{ticker}/documents/{section}`
- `GET /api/v2/companies/{ticker}/research` — a full evidence-grounded company brief
- `POST /api/v2/qa` — free-form, evidence-grounded question answering

Configuration is environment-driven: `FINQA_V2_API_HOST/PORT/CORS_ORIGINS`, `FINQA_V2_API_KEY` (optional bearer key), `FINQA_V2_QA_RATE_LIMIT`, `FINQA_V2_DB_PATH`. See `finqa_v2/api/config.py` for the full list.

### Dashboard

```bash
cd dashboard_v2
npm install
npm run dev -- --port 5174
```

Set `VITE_API_BASE_URL` in `dashboard_v2/.env.local` if the API isn't on `localhost:8010`. Pages: a market overview, a searchable/filterable company list, a per-company page (Financials / Ratios / Trends / Segments / Peer Comparison, each respecting a consolidated/standalone toggle), a metric-based Rankings leaderboard, a Research page (a full evidence-grounded brief per company), and a Financial QA chat where every answer's claims expand into their supporting evidence.

### Example questions that work today

- *"What was TCS's revenue in FY2026?"* — a grounded numeric fact.
- *"What is RELIANCE's ROE?"* — a ratio, with the calculation and its inputs shown on request.
- *"Compare TCS and Infosys on profitability."* — a ranked, evidence-backed comparison.
- *"Which segment contributed most to Reliance's revenue growth?"* — full segment attribution, every segment named.
- *"Why did HCLTECH's profitability decline?"* — causal hypotheses, each structurally tested against the numbers and (where available) transcript evidence.
- *"TCS management said growth was driven by the BFSI segment — is that supported?"* — a direct check of a stated claim against the reported figures and filings.

---

## Evaluation

```bash
python -m unittest discover -s evaluation

# score the deterministic pipeline (no LLM calls)
python -m evaluation.runners.v2_runner --dataset evaluation/datasets/finqa_v2_eval.jsonl --no-retriever

# regenerate the internal 850-question benchmark
python -m evaluation.datasets.finqa_india.build

# compare the full pipeline against simpler baselines on a sample
python -m evaluation.baselines.runner --dataset evaluation/datasets/finqa_india.jsonl --sample 20 --llm
```

The internal benchmark spans factual, numerical, comparison, multi-step, causal ("why"/"how"), cross-document, analytical, and adversarial questions across all 50 NIFTY 50 companies, with numeric answers checked against the Financial Engine's own ground truth. A regression gate (`evaluation/regression/`) compares any new run against a pinned baseline and fails the check if key metrics regress beyond a tolerance.

---

## Known, honest limitations

- **Historical depth**: the ingested data currently covers the most recent annual and quarterly filings only (not multiple years back) — a question about an older period gets an honest "not available," never a wrong year's figure.
- **Segment margin is never shown**, only segment revenue — filings disclose one but not the other, and the system doesn't approximate it.
- **The dashboard's consolidated/standalone toggle is manual** by design — a company that files only one basis won't have the other silently substituted in.
- **PostgreSQL + pgvector support exists and is tested**, but the dashboard/API run against SQLite by default; switching backends is a configuration change, not a code change.

---

Licensed under MIT — see [`LICENSE`](./LICENSE).
