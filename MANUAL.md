# Fin·QA v2 — Technical Manual

This is the reference manual for Fin·QA v2: what each part of the system does, how the
pieces fit together, every configuration knob, and how to operate it in development and
in production. The [README](README.md) is the pitch and the quick start; this document is
what you read when you need to change something, debug something, or understand a design
decision.

Fin·QA v2 lives entirely under `finqa_v2/` (imported as `finqa_v2.*`, run as
`python -m finqa_v2.<module>`) and `dashboard_v2/` for the frontend. An earlier iteration
of the project is preserved under `archive/` — untouched, still runnable, not covered by
this manual except where noted.

## Table of contents

1. [System overview](#1-system-overview)
2. [Repository layout](#2-repository-layout)
3. [Data model and storage](#3-data-model-and-storage)
4. [Building the dataset](#4-building-the-dataset)
5. [The Financial Engine](#5-the-financial-engine)
6. [Document intelligence and retrieval](#6-document-intelligence-and-retrieval)
7. [Evidence, claims, and the tool layer](#7-evidence-claims-and-the-tool-layer)
8. [Query planning and reasoning](#8-query-planning-and-reasoning)
9. [Hypothesis testing and cross-validation](#9-hypothesis-testing-and-cross-validation)
10. [Verification](#10-verification)
11. [LLM providers and budgets](#11-llm-providers-and-budgets)
12. [REST API reference](#12-rest-api-reference)
13. [Dashboard](#13-dashboard)
14. [Deployment](#14-deployment)
15. [Observability](#15-observability)
16. [Security](#16-security)
17. [Evaluation framework](#17-evaluation-framework)
18. [Known limitations](#18-known-limitations)
19. [Development workflow](#19-development-workflow)
20. [Troubleshooting](#20-troubleshooting)
21. [Full environment variable reference](#21-full-environment-variable-reference)
22. [Full command reference](#22-full-command-reference)

---

## 1. System overview

Fin·QA answers questions about NIFTY 50 companies by routing them through a pipeline that
never lets an LLM compute or invent a number:

```
XBRL filings + results PDFs + transcripts + presentations
        │
        ▼
normalize/  →  SQLite or PostgreSQL+pgvector
        │
        ▼
engine/  (ratios, growth, valuation, segments, decomposition — pure Python, no LLM)
        │
        ├── documents/ + retrieval/  (chunking, BM25, dense embeddings, hybrid fusion, rerank)
        ▼
planner/  (rules-based, optionally LLM-assisted)
        ▼
tools/  (~15 typed functions — the only way a question touches data or documents)
        ▼
reasoning/ orchestrator
   ├── hypothesis/   — "why" questions: decompose → generate causes → structurally test
   ├── crossval/     — "is this claim true": extract claim → check against data → adjudicate
   └── evidence/     — everything else: assemble an Evidence Workspace, build a Claim Graph
        ▼
verification/  (independently recomputes every calculation, checks every citation)
        ▼
api/  (FastAPI, thin transport, computes nothing)
        │
        └── dashboard_v2/  (React/Vite)
```

Every stage produces artifacts the next stage consumes; none of them talk to an LLM except
`planner/`, `reasoning/`, and — as a phrasing assist only — `hypothesis/`. The Financial
Engine, the retrieval stack, the tool layer, and verification are pure, deterministic
Python with no model calls, and each has a "run with zero LLM calls" path that still
produces a complete, cited answer, just in plainer prose.

### Design invariants

These are enforced in code, not just documented:

- **A missing value is `None`, never `0` and never estimated.** `FinancialFact.value`,
  every `EngineResult.value`, every `Evidence.value` — absence is explicit everywhere.
  Ratios and metrics that can't be computed cleanly return `None` plus a `limitations`
  string explaining why (see `finqa_v2/models.py`, `finqa_v2/engine/engine.py`).
- **Every number in a synthesized answer traces to a real `Calculation` or `Evidence`
  object with a stable id.** `ClaimGraph` (`finqa_v2/evidence/graph.py`) is the structure
  that makes "why does the system believe this" answerable down to the evidence id.
- **The reasoning LLM is handed a closed set of facts (the Evidence Workspace) and told
  to cite an evidence id for every claim; it is never given open internet or model-parametric
  license.** `finqa_v2/reasoning/synthesize.py`'s system prompt states this explicitly, and
  `parse_synthesis` drops any claim that cites an id not actually in the workspace.
- **Verification runs after synthesis, independently of the LLM that wrote the answer.**
  `finqa_v2/verification/verifier.py` recomputes every pinned calculation from its inputs
  and reconciles every number mentioned in the final prose against the evidence it should
  match — a claim that fails is downgraded, or the whole answer is abstained with a
  `[unverified]` prefix.
- **Consolidated and standalone financial statements are never silently substituted for
  each other.** A company that files only one basis (most insurers) shows the other basis
  as genuinely unavailable; the dashboard exposes a manual toggle instead of guessing.

---

## 2. Repository layout

```
finqa_v2/              The system this manual describes.
├── models.py            Frozen dataclasses for every domain entity (Company, FinancialFact,
│                        Segment, DocumentChunk, SharePrice, ...) and their enums.
├── repositories.py      runtime_checkable Protocols the rest of the system depends on —
│                        this is the seam that lets SQLite and PostgreSQL be interchangeable.
├── db.py                repositories_from_env() — picks SQLite or Postgres from FINQA_PG_URL.
├── sqlite/               SQLite schema + repository implementation.
├── postgres/             PostgreSQL + pgvector schema, repository implementation, migration.
├── normalize/            XBRL → canonical FinancialFact / Segment records.
├── engine/               The deterministic Financial Engine (§5).
├── documents/            PDF → structure-aware, page-anchored DocumentChunks.
├── retrieval/            BM25 + dense embeddings + hybrid fusion + reranking (§6).
├── evidence/             Evidence / Claim / Calculation models, the Evidence Workspace,
│                        the Claim Graph (§7).
├── tools/                The typed Tool Registry (§7).
├── planner/              Query planning, rules-based and LLM-assisted (§8).
├── llm/                  LLM provider abstraction + rate/cost budgets (§11).
├── reasoning/            The Reasoning Orchestrator (§8).
├── hypothesis/           Causal "why" question workflow (§9).
├── crossval/             "Is management's claim supported?" workflow (§9).
├── verification/         Post-synthesis recomputation and citation checking (§10).
├── claimgraph/           Read/explain/export layer over the Claim Graph.
├── prices/               EOD share price import, for valuation ratios.
├── dataset/              One-command dataset rebuild + coverage audit (§4).
├── scale/                Footprint measurement and scale projection.
├── observability/        Prometheus metrics + structured logging (§15).
└── api/                  FastAPI app (§12).

dashboard_v2/           React (Vite) frontend over the API (§13).
evaluation/             Internal benchmark, evaluators, baseline comparisons (§17).
deployment/             Docker Compose stack, Dockerfiles, Grafana/Prometheus config (§14).
data_extraction/        Fetches raw XBRL/PDF filings from BSE/NSE (shared with the archived v1).
database/data/          Generated data artifacts (finqa_v2.db, BM25 index, vector index) — gitignored.
archive/                A complete, still-runnable earlier version of the project
                        (data_analysis/, rag/, qa_router/, llm_router/, orchestrator/,
                        fin_llm_platform/, its own api/ and dashboard/). Not touched by
                        anything in finqa_v2/; kept as a reference point, not deleted.
```

`finqa_v2/` and `dashboard_v2/` are additive: nothing in them modifies `archive/`, and the
two share only the raw data under `data_extraction/data/` and `database/data/` (the
`finqa_v2` dataset pipeline reads XBRL/PDF inputs from there, but writes its own
`finqa_v2.db`, separate from the archived `financial_intelligence.db`).

---

## 3. Data model and storage

### Core entities (`finqa_v2/models.py`)

| Entity | Notes |
|---|---|
| `Company` | ticker, exchange, ISIN, sector, aliases. |
| `Index` / `IndexMembership` | Point-in-time universe membership (`valid_from`/`valid_to`); NIFTY 50 is just the one index row shipped today — nothing about the universe is hardcoded. |
| `FinancialFact` | One (company, metric, basis, period, ...) grain. `value=None` means "not reported or not cleanly mappable" — it is never zero-filled. `mapping_confidence` / `mapping_reason` record why a fact is flagged for review. |
| `Segment` / `SegmentFact` | Reportable-segment revenue (not margin — see §18). |
| `DocumentMeta` / `DocumentChunk` | A filing PDF and its structure-aware, page- and section-anchored chunks. |
| `SharePrice` | EOD close/VWAP/volume, for valuation ratios. |

### Repository layer

Every read/write goes through a `runtime_checkable` Protocol in `repositories.py`
(`CompanyRepository`, `FinancialFactRepository`, `DocumentRepository`, `SegmentRepository`,
`SharePriceRepository`, bundled as `Repositories`). Two implementations satisfy the same
Protocols:

- **`finqa_v2/sqlite/`** — the default. `SqliteRepositories`, schema in `schema_v2.sql`.
  A `_ThreadSafeConnection`/`_MaterializedCursor` pair serializes access behind one lock and
  fully materializes results before releasing it — `sqlite3`'s `threadsafety == 3` describes
  the C library, not a guarantee about the Python wrapper under real concurrent access, and
  the naive version corrupted state under load (see §14 and §18's fixed-bugs history in
  `docs/roadmap.md` if you're chasing a similar bug in your own fork).
- **`finqa_v2/postgres/`** — `PgRepositories`, schema in `schema_pg.sql` (adds `pgvector`
  for `document_chunks.embedding`). Reuses the SQLite repository classes' logic unchanged,
  fed through a `_PgConn` adapter that rewrites SQL dialect differences (`?` → `%s`,
  `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`, etc.) — the engine, tools, and reasoning
  code above the repository layer do not know or care which backend is live.

`finqa_v2/db.py:repositories_from_env()` returns `PgRepositories` if `FINQA_PG_URL` (or
`DATABASE_URL`) is set, otherwise `SqliteRepositories`. Switching backends is a
configuration change, not a code change.

### Data artifacts

All generated data lives under `database/data/` (gitignored — regenerate, don't expect it
in a fresh clone):

| File | What it is | Regenerated by |
|---|---|---|
| `finqa_v2.db` | The SQLite database (or the source loaded into Postgres). | `python -m finqa_v2.dataset.build` |
| `finqa_v2_bm25.pkl` | Pickled BM25 lexical index. | `python -m finqa_v2.retrieval.build_indexes` |
| `finqa_v2_vec/` | Dense vector index (faiss) + `model.txt` naming the embedding model used to build it. | `python -m finqa_v2.retrieval.build_indexes --vector` |
| `scale_report.json` | Footprint/latency/projection report. | `python -m finqa_v2.scale.report --json ...` |

---

## 4. Building the dataset

`python -m finqa_v2.dataset.build` runs six steps in order, each idempotent and each
individually re-runnable:

1. **`import`** (`finqa_v2.import_from_v1`) — company/index metadata from the raw NSE/BSE
   universe file into `companies`, `indices`, `index_memberships`.
2. **`facts`** (`finqa_v2.normalize.backfill`) — XBRL → canonical `FinancialFact` rows, via
   the metric registry in `normalize/metrics.py` and the arithmetic-identity checks in
   `normalize/validate.py` (relative tolerance, `max(₹1, 0.05% of the largest operand)` —
   appropriate at ₹10¹¹–10¹² scale).
3. **`segments`** (`finqa_v2.normalize.backfill_segments`) — reportable-segment revenue
   from the same raw XBRL contexts.
4. **`prices`** (`finqa_v2.prices.import_prices`) — EOD share prices from CSV exports, used
   for P/E, P/B, EV/EBITDA, and yield calculations.
5. **`docs`** (`finqa_v2.documents.backfill`) — PDF filings → page-anchored,
   section-classified, structure-aware chunks (`--skip-docs` to omit; `--no-tables` for a
   faster run without table extraction, which is the slow part).
6. **`audit`** (`finqa_v2.dataset.audit`) — a coverage report: per-company fact/segment/
   document/price completeness, an aggregate 0–100 score, and a `critical` flag for members
   with no facts, no balance sheet, or facts with no annual period. `--check` exits 1 on a
   critical gap, for CI use.

```bash
python -m finqa_v2.dataset.build                 # full run
python -m finqa_v2.dataset.build --skip-docs      # skip the slow PDF step (~2 min total)
python -m finqa_v2.dataset.build --from segments  # resume from a specific step
python -m finqa_v2.dataset.build --company TCS    # single company (development)
```

Then build the search indexes (a separate step, since it needs `finqa_v2.db` to exist
first):

```bash
python -m finqa_v2.retrieval.build_indexes            # BM25 (always; fast, no GPU needed)
python -m finqa_v2.retrieval.build_indexes --vector    # + dense embeddings (add --device cuda on a GPU)
```

### Where the raw data comes from

`data_extraction/` (shared with `archive/`) fetches XBRL filings and results PDFs from BSE
via `src/fetch/`, and — for the narrative corpus behind causal/"why" questions —
`src/fetch/annual_reports.py` sweeps BSE announcements for earnings-call transcripts,
investor presentations, annual reports, and BRSR filings:

```bash
cd data_extraction
python -m src.fetch.annual_reports --symbols TCS --years 3 --dry-run
python -m src.fetch.annual_reports --all --years 1.5 --kinds transcript investor_presentation
```

Transcripts matter more than they might look: a "why did operating margin change" answer
can only be `supported` (rather than `partially_supported`) when a retrieved passage from
an earnings call actually corroborates a structurally-consistent cause — see §9.

---

## 5. The Financial Engine

`finqa_v2/engine/engine.py`'s `FinancialEngine` is the single source of numeric truth. It
is pure Python over the repository layer — no LLM, no network, no external service — built
so the same formula always produces the same figure given the same facts, and so a formula
change is one line in one file, not a prompt edit.

### Core pipeline

`engine/records.py` regroups raw facts into `PeriodRecord`s (one duration record per
period — P&L/cash-flow — with the same-period-end balance-sheet snapshot merged in), then:

- `engine/derive.py` computes derived quantities not directly tagged in XBRL (`ebit`,
  `ebitda`, `total_debt`, `net_debt`, `capex`, `shares_outstanding`).
- `engine/ratios.py` is a `RatioSpec` registry (~17 ratios plus aliases): ROE, ROA, ROCE,
  EBITDA/EBIT/net/PBT margin, debt-to-equity, interest coverage, current ratio, asset
  turnover, effective tax rate, cash ratio, equity-to-assets, payout ratio, plus
  bank-specific NIM and credit cost.
- `engine/valuation.py`'s `ValuationEngine` computes P/E, P/B, EV/EBITDA, market cap,
  earnings yield, and dividend yield against the nearest share price at or before the
  period end. For banks with no reported EPS line, EPS is derived as
  `net_profit / shares_outstanding`; for banks with no EBITDA line, EV/EBITDA falls back to
  `bank_operating_profit` (pre-provision operating profit) and is flagged in `limitations`
  as a proxy. Insurers with no disclosed share count get `None` for P/E and P/B rather than
  a fabricated figure.
- `engine/growth.py` computes YoY/QoQ percentage change, absolute change, and CAGR.
- `engine/decompose.py` does DuPont ROE decomposition (net margin × asset turnover × equity
  multiplier, reconciled against the actual ratio) and a net-margin bridge (splitting a
  margin change into a revenue-effect and an expense-effect in percentage points).
- `engine/segments.py`'s `SegmentEngine` computes per-segment revenue contribution and, for
  growth questions, each segment's **share of the total change** — the basis for answering
  "which segment drove growth."
- `engine/calculator.py`'s `calculate(expr, **vars)` is an AST-restricted evaluator (only
  numeric literals, arithmetic operators, and names bound from `vars` — no imports,
  attribute access, or arbitrary calls) for ad hoc formula evaluation from a tool call.

Every entry point returns an `EngineResult` (`value`, `unit`, `formula`, `inputs` as
`FactRef`s back to the source facts, `limitations`). A metric that can't be computed
cleanly — a bank with no `revenue` line, a period the dataset doesn't cover, an insurer
with no share count — comes back `value=None` with a specific reason in `limitations`,
never a zero or an estimate.

### Bank and insurer handling

Indian banks and insurers file in RBI/IRDAI formats that don't carry a `revenue` tag; the
engine's `top_line()` helper falls back to `total_income` wherever `revenue` would
otherwise be used (net profit margin, asset turnover, DuPont, net-margin bridge), so these
companies get a real ratio surface instead of a wall of `None`.

### Period selection

Engine calls accept `"latest"`, `"latest_annual"`, `"latest_quarter"`, a bare year
(`2026`), a fiscal-year string (`"FY2026"`), a fiscal-year-and-quarter tuple/string
(`"FY2026Q1"` or `(2026, 1)`), or an explicit year in the question text (`"in the year
2021"`). **Bare `"latest"` on a plain ratio resolves to the most recent period of any
kind** — if a company has quarterly filings, that can be a quarter, not a year, which
under-reports an annualized ratio like ROE by roughly 4x. Every caller in this codebase
(the reasoning orchestrator, the raw API routers) defaults an *unstated* period to
`"latest_annual"` rather than bare `"latest"` for exactly this reason — keep that default
if you add a new caller.

---

## 6. Document intelligence and retrieval

### Ingestion (`finqa_v2/documents/`)

PyMuPDF-based extraction (`extract.py`) pulls clean Unicode text plus heading candidates
(font-size jumps, bold, ALL-CAPS short lines) and tables per page. `sections.py` classifies
contiguous page spans into one of ~15 section types (`auditors_report`,
`financial_results`, `balance_sheet`, `segment_information`, `notes`, `mda`,
`risk_factors`, `board_report`, `corporate_governance`, `brsr`, `earnings_call`, etc.).
`chunk.py` then packs prose into ~900-character chunks with ~120-character paragraph-level
overlap (each table becomes its own chunk, never split or merged into prose), tagging each
chunk with its section, page range, financial year, document type, and — where detected —
the segment name it discusses. `pipeline.py` de-duplicates on a content hash of the source
file, not on title, since two distinct filings can share a title.

### Retrieval (`finqa_v2/retrieval/`)

The full pipeline is: **metadata pre-filter → BM25 + dense vector search → reciprocal-rank
fusion → optional cross-encoder rerank → top-k**. Each stage is independently swappable:

- `lexical.py`'s `BM25Index` — no torch dependency, always available. Uses a lazily-built
  inverted index over `(company_id, financial_year, document_type, section)` so a filtered
  search scores only the matching subset instead of the full corpus (this was a measured
  ~35x latency fix at Phase 16 — see `docs/roadmap.md` if you're auditing the history).
- `embed.py` — `SentenceTransformerEmbedder` (`all-MiniLM-L6-v2` by default, GPU-aware) or
  a dependency-free `HashEmbedder` for tests.
- `vector.py`'s `VectorIndex` — faiss `IndexFlatIP` when available, exact numpy matmul
  otherwise.
- `fuse.py` — reciprocal rank fusion (k=60) across the lexical and vector rankings.
- `rerank.py`'s `CrossEncoderReranker` (`ms-marco-MiniLM-L-6-v2`) — built and tested but
  **not enabled by default** (`FINQA_V2_RERANK=0`); see the callout below.
- `retriever.py`'s `HybridRetriever` ties it together: `retrieve(query, k, mode, filters)`
  with `mode` ∈ `lexical`/`vector`/`hybrid` (silently downgrading `hybrid` to `lexical`
  when no vector index is present).

**Why reranking defaults off.** It was measured, not assumed: on the 50-question
`cross_document` slice of the internal benchmark, enabling the cross-encoder added ~265–300
ms per retrieval call (candidate_k=40 passages through a transformer model, and a causal or
cross-validation question fires several retrieval calls) for an inconclusive-to-negative
quality effect — a small recall gain in lexical-only mode, a small MRR *loss* in hybrid mode
(the mode the API runs by default). Set `FINQA_V2_RERANK=1` if a larger evaluation run on
your own data justifies the cost.

**Why hybrid mode isn't lexical-only or vector-only by default.** Two independent
evaluations disagree on which is better: an 18-case hand-built set favored lexical, a
50-question benchmark slice favored hybrid slightly. Given genuinely inconclusive evidence,
the default was deliberately left as `hybrid` rather than flipped for a speed gain that
would trade away an unknown quality risk.

Run `python -m finqa_v2.retrieval.evaluate` against `retrieval/eval_cases.jsonl` for
Recall@k / MRR / p50-latency per mode on your own corpus before changing either default.

---

## 7. Evidence, claims, and the tool layer

### Evidence Workspace (`finqa_v2/evidence/`)

Every fact, ratio, growth figure, segment number, or retrieved document passage that
enters a question's answer is first wrapped as an `Evidence` object (`models.py`) — typed,
carrying a `confidence` in `[0, 1]`, a citation back to its source, and (for a computed
number) an attached `Calculation` recording the formula and its pinned inputs, each of
which is itself an `Evidence` id. `workspace.py`'s `EvidenceSet` is the **Evidence
Workspace**: an ordered, deduplicated collection that every part of the reasoning layer
reads from and writes into.

`confidence.py` documents the exact heuristics: an exact fact starts at 0.98 (0.72 if
flagged for review by the normalization arithmetic checks), a ratio at 0.90, a document
passage somewhere in `[0.30, 0.85]` depending on retrieval rank/score. A claim's confidence
is the mean of its supporting evidence confidences times a status factor; the graph's
overall confidence is floored at 0.4 if any claim is `NOT_SUPPORTED`.

`build.py` holds the adapters that turn raw output from the engine, the retriever, or the
segment engine into `Evidence` — this is the only sanctioned path from "raw computed or
retrieved thing" to "something the reasoning layer can cite."

`graph.py`'s `ClaimGraph` assembles `Claim`s (each with a `ClaimStatus` ∈ `SUPPORTED` /
`PARTIALLY_SUPPORTED` / `NOT_SUPPORTED` / `INSUFFICIENT_EVIDENCE`) and exposes
`to_response()`, which produces the response schema every answer ultimately returns:

```json
{
  "answer": "...",
  "confidence": 0.91,
  "claims": [...],
  "calculations": [...],
  "evidence": [...],
  "sources": [...],
  "limitations": [...]
}
```

`finqa_v2/claimgraph/view.py`'s `ClaimGraphView` is the read-side layer over the same
graph: `explain(claim)` returns one claim's full provenance subtree, `to_graph()` /
`to_mermaid()` export a typed node/edge graph for visualization, and `to_dict(reachable_only=True)`
(what the API always uses) trims the export to only what a claim actually cites, instead of
dumping the entire workspace.

### Tool layer (`finqa_v2/tools/`)

Exactly 15 typed tools are the **only** way any question — deterministic or LLM-planned —
touches data or documents:

| Group | Tools |
|---|---|
| Financial (8) | `get_metric`, `get_ratio`, `get_growth`, `get_cagr`, `compare_companies`, `compare_periods`, `get_segment_data`, `decompose_metric` |
| Documents (3) | `search_documents`, `get_document_section`, `get_source` |
| Math (1) | `calculate` |
| Company (3) | `get_company`, `get_peers`, `get_index_members` |

Each tool is a `base.py:Tool` wrapping a pydantic-validated function; `.call()` never
raises — it returns a `ToolResult{ok, value, error, latency_ms, evidence}` even on bad
input or an internal exception, logged at the appropriate level. `ToolRegistry` keeps a
call trace (used for both debugging and the `finqa_tool_calls_total` Prometheus metric).
`.schema()` on each tool produces an LLM-function-calling-compatible JSON schema, so the
same registry can be handed directly to a planner or a reasoning LLM.

---

## 8. Query planning and reasoning

### Planner (`finqa_v2/planner/`)

`rules.py` is a deterministic planner: ticker/alias/company-name matching, regex period
extraction (`FY2026`, `FY26 Q1`, `"for the year ended 2021"`, `"last N years"`), a
metric-phrase table, and an ordered set of intent rules producing a `QueryPlan`
(`intent`, `companies`, `periods`, `metrics`, `tools`, `needs_documents`,
`needs_calculation`). It is both the always-available fallback and, on its own, a strong
baseline (0.94 intent accuracy on the internal eval set with zero LLM calls).

`planner.py`'s `QueryPlanner` calls an LLM (when a provider is configured) to extract
intent and entities, then **always derives the actual tool list from the deterministic
rules mapping** rather than trusting the LLM's tool choices — measured to be the more
reliable half of the split (perfect on-eval-set quality from the LLM's language
understanding, more reliable tool selection from the deterministic mapping). If the LLM
call fails, times out, returns invalid JSON, or the budget guard fires, `_merge` falls back
to the pure-rules plan with no interruption.

### Reasoning Orchestrator (`finqa_v2/reasoning/orchestrator.py`)

`ReasoningOrchestrator.answer(question)` runs one bounded pass:

1. **Plan** the question (planner, above).
2. **Run** each planned tool (max 6 per question) through the registry, tracing every
   call.
3. **Rehydrate** the tools' evidence payloads into a shared `EvidenceSet`.
4. Depending on intent: causal questions route into `hypothesis/` (§9), claim-verification
   questions into `crossval/` (§9); everything else goes straight to synthesis.
5. **Synthesize**: an LLM writes the final answer from the workspace only
   (`synthesize.py`'s system prompt forbids inventing numbers or citations and requires an
   evidence id per claim; `parse_synthesis` drops any claim citing an id not actually in
   the workspace) — or, with no provider configured, `deterministic_answer()` stitches the
   facts into plain sentences with zero LLM calls.
6. **Build** the Claim Graph (§7) and **verify** it (§10) before returning.

A question naming fewer than two companies for a comparison intent gets its universe
resolved automatically via `get_peers` (same sector) or `get_index_members` (default
NIFTY 50), capped at 12 companies.

---

## 9. Hypothesis testing and cross-validation

Two specialized workflows sit inside the reasoning pass for the two hardest question
types. Both are **deterministic-first**: an LLM, if configured, only proposes extra
candidate phrasings — it never classifies a verdict and never sees the raw documents
directly.

### Hypothesis testing (`finqa_v2/hypothesis/`) — "why did X happen?"

1. `detect.py` quantifies the change (YoY growth for a plain metric; a two-endpoint
   diff for a ratio with no direct fact series, e.g. a margin).
2. `decompose.py` builds a `DecompositionView`: ~10 P&L/cash-flow component growth rates,
   the net-margin bridge, a two-endpoint DuPont diff, and segment growth attribution — each
   keyed into the shared Evidence Workspace so a hypothesis can cite the exact number it's
   built on.
3. `generate.py` reads deterministic candidate causes straight off the decomposition
   (a cost line growing faster/slower than revenue, the dominant DuPont factor, a segment
   responsible for a large share of the change), each tagged with the structural signal
   that produced it; an LLM, if wired, can append additional candidate phrasings
   (deduplicated by token overlap).
4. `validate.py` structurally re-checks each hypothesis' signal against the actual numbers
   (`agrees` / `contradicts` / `unrelated` / `no_data`), then retrieves a corroborating
   document passage per candidate.
5. `classify()` combines the structural verdict and document corroboration into one of the
   four `ClaimStatus` values — a cause that's both numerically consistent *and* mentioned
   in a retrieved transcript passage is `SUPPORTED`; numerically consistent alone is
   `PARTIALLY_SUPPORTED`; contradicted by the numbers is `NOT_SUPPORTED`.

### Cross-validation (`finqa_v2/crossval/`) — "management said X, is it true?"

1. `extract.py` pulls the checkable assertion out of the question (subject, direction,
   claimed mechanism, claimed magnitude) via a compact regex/phrase-table extractor — an
   LLM, if wired, can only backfill a missing subject/direction/mechanism, never a number.
2. `checks.py` runs structured checks: directional agreement, magnitude tolerance
   (`max(1pp, 15% of the claimed value)`), a mechanism check (a claimed cost-driven margin
   move is checked against actual cost-line growth; a claimed volume/pricing/demand-driven
   move returns `no_data` — the system has no structured proxy for volume or price
   separately from revenue, and says so rather than guessing), and segment-attribution
   matching (including acronym expansion, e.g. "BFSI" → "Banking, Financial Services and
   Insurance").
3. `corroborate.py` checks the same claim against retrieved filing text.
4. `adjudicate.py` combines both into a verdict: contradicted numbers → `NOT_SUPPORTED`;
   agreement plus document corroboration → `SUPPORTED`; agreement alone or corroboration
   alone → `PARTIALLY_SUPPORTED`; neither → `INSUFFICIENT_EVIDENCE`.

The **honesty rule** running through both workflows: a mechanism the system has no way to
check (volume, pricing, qualitative demand commentary) is reported as `no_data`, never
approximated as agreement or disagreement.

---

## 10. Verification

`finqa_v2/verification/verifier.py`'s `Verifier` runs **after** synthesis and **does not
trust the LLM's own arithmetic or citations**:

- **`check_calculation`** re-runs every pinned calculation independently from its recorded
  inputs (via the same AST-restricted `calculate()` the engine used originally) and
  compares the result — `recomputed` (matches) or `does_not_recompute` (doesn't).
- **`check_claim`** confirms every cited evidence/calculation id still exists in the
  workspace (`citation_missing` if not) and flags `citation_weak` when a qualitative claim
  shares no wording with the passage it cites.
- **`check_answer_numbers`** finds, for every ratio/growth/fact evidence item, the sentence
  in the final prose that should be stating it, extracts the figure in the right unit
  family, and reconciles it within tolerance (`max(0.5pp, 2%)` for ratios, 3% for INR
  amounts) — period-aware, so a sentence naming the wrong fiscal year is caught.

`Verifier._adjudicate` then applies the outcome: a failed claim is downgraded to
`not_supported` with its confidence cut; a bad calculation adds a limitation; and if the
answer's own headline figures fail reconciliation as a body (two or more mismatches with
no confirmations, or a mismatch-majority), the entire answer is **abstained** — prefixed
`[unverified]`, confidence capped at 0.3 — rather than shown as a confident wrong number.

This pass is deterministic and independent of whichever LLM (or no LLM) produced the
prose, so it catches synthesis errors from any provider.

---

## 11. LLM providers and budgets

`finqa_v2/llm/provider.py` defines one `LLMProvider` protocol
(`complete(prompt, system=, json_object=, ...) -> str`) with three implementations:

| Provider | Class | Notes |
|---|---|---|
| Groq (default, free tier) | `GroqProvider` | Reads `GROQ_API_KEY`. Obeys `Retry-After` on a 429, retries once, then raises. |
| Anthropic (paid, optional) | `AnthropicProvider` | Reads `ANTHROPIC_API_KEY`. Calls the Messages API directly. Requires `pip install -e ".[anthropic]"`. |
| None | `NullProvider` | Always raises — every caller falls back to its deterministic path. Used when no key is configured. |

`provider_from_env()` returns `GroqProvider` if a key is present and
`FINQA_LLM_DISABLED != 1`, else `NullProvider`. Choosing Anthropic is a separate, explicit
call (`anthropic_provider_from_env()`) — the free-tier default never changes silently.

### Budget guards (`finqa_v2/llm/limits.py`)

Groq is metered by `RateBudget`: hard caps that **raise** (`max_requests=60`/process,
`tpd_limit=180000` tokens/day) and soft throttles that **sleep** on a sliding 60-second
window (`rpm_limit=25`, `tpm_limit=7000`). All four are overridable via
`FINQA_LLM_MAX_REQUESTS` / `FINQA_LLM_RPM` / `FINQA_LLM_TPM` / `FINQA_LLM_TPD`. When the
hard cap fires, the planner and reasoning layers catch `LLMBudgetExceededError` and fall
back to their deterministic paths — a question never fails outright because of a spent
budget, it just answers more plainly.

Anthropic is metered by `CostBudget`: a **hard dollar cap**, checked and reserved *before*
every call from a conservative token-count estimate, then reconciled against the real
`usage` the API returns. Appropriate for a key with a known, finite balance rather than a
free-tier rate limit.

`FINQA_LLM_DISABLED=1` is a hard kill switch regardless of provider — useful for CI or a
demo you want to guarantee costs nothing.

---

## 12. REST API reference

`finqa_v2/api/` is a FastAPI app, deliberately thin: every deterministic endpoint either
wraps one Tool Registry call or reads directly from `FinancialEngine`/`SegmentEngine`; `/qa`
and `/research` are the unmodified `ReasoningOrchestrator`. No calculation exists twice.
Repositories, the engine, the retriever, the registry, and the orchestrator are built once
at startup (`lifespan`) and shared across requests via `app.state` — never rebuilt per
call.

Run it with `finqa-api-v2` (installed console script) or
`uvicorn finqa_v2.api.main:app --port 8010`. Interactive docs at `/docs`.

### Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/health` | Liveness: DB / engine / retriever / LLM-provider status. Never rate-limited or key-gated. |
| GET | `/metrics` | Prometheus exposition format. Never rate-limited or key-gated. |
| GET | `/api/v2/companies` | List the current index universe. |
| GET | `/api/v2/companies/{ticker}` | Company profile. |
| GET | `/api/v2/companies/{ticker}/peers` | Same-sector active peers. |
| GET | `/api/v2/companies/{ticker}/financials` | Raw metric lookup (`get_metric`). |
| GET | `/api/v2/companies/{ticker}/ratios` | Ratio lookup (`get_ratio`). |
| GET | `/api/v2/companies/{ticker}/ratios/decompose` | DuPont / net-margin bridge (`decompose_metric`). |
| GET | `/api/v2/companies/{ticker}/growth` | YoY/QoQ growth (`get_growth`). |
| GET | `/api/v2/companies/{ticker}/growth/cagr` | CAGR (`get_cagr`). |
| GET | `/api/v2/companies/{ticker}/segments` | Segment revenue + contribution (`get_segment_data`). |
| GET | `/api/v2/companies/{ticker}/segments/growth` | Segment growth attribution (direct `SegmentEngine` call — no tool exists for this since it's not on the LLM-facing §19 list, and a REST layer isn't bound by that boundary). |
| GET | `/api/v2/rankings` | Cross-company ranking on a metric (`compare_companies`). |
| GET | `/api/v2/companies/{ticker}/documents/{section}` | All chunks of one filing section for a company. |
| GET | `/api/v2/sources/{document_id}` | Citation detail for one document. |
| GET | `/api/v2/search` | Free-form document search (`search_documents`). |
| GET | `/api/v2/companies/{ticker}/research` | A full evidence-grounded company brief (rate-limited: `FINQA_V2_QA_RATE_LIMIT`). |
| POST | `/api/v2/qa` | Free-form, evidence-grounded question answering, body `{"question": "...", "use_llm": true}` (rate-limited: `FINQA_V2_QA_RATE_LIMIT`). |

Every ratio/growth/segment/financials endpoint accepts `period` (defaults to
`latest_annual`, not bare `latest` — see the period-selection note in §5) and `basis`
(`consolidated`, the default, or `standalone`).

### Error handling

Errors are JSON: `{"error": "...", "detail": "..."}`. `ApiError` subclasses map to status
codes (`CompanyNotFoundError` → 404, `EngineNotReadyError` → 503, an invalid tool input →
422). A catch-all handler logs the real exception server-side and never leaks it to the
client.

### Response sanitization

Every response — deterministic endpoints included — passes through
`sanitize.py:strip_server_paths`, which recursively removes any `"uri"` key from the
payload. `Citation.uri` internally holds the server-side filesystem path to a source PDF;
this is useful inside the reasoning/verification layers and must never reach a client.
Applied generically (not endpoint-by-endpoint) because a `uri` key can appear nested
anywhere inside an evidence or claim-graph payload, not just in an obvious `sources` field.

### Caching

`/qa` and `/research` keep an in-process LRU cache (`api/cache.py`, no TTL, 256 entries
each) keyed on the exact request. The dataset is immutable for a running container's
lifetime, so an identical question always produces an identical answer — caching is exact,
not an approximation. A real data update requires a restart, which naturally clears the
cache. The cache lives in the API layer only; `ReasoningOrchestrator.answer()` itself is
never cached, so eval runs and tests always exercise the real pipeline.

---

## 13. Dashboard

`dashboard_v2/` is a React 18 + Vite 5 single-page app (port 5174 by default) talking to
the API above. No server-side rendering, no state framework beyond React's own hooks.

```bash
cd dashboard_v2
npm install
npm run dev -- --port 5174
```

Set `VITE_API_BASE_URL` (a build-time environment variable, since it's baked into the
browser bundle) if the API isn't on `localhost:8010`.

### Structure

- `src/api/client.js` — a thin fetch wrapper, one method per API endpoint.
- `src/api/useApi.js` — a fetch-on-mount hook with request cancellation, used by every
  page instead of a raw `useEffect`.
- `src/components/EvidenceClaims.jsx` — the one component both the Research and QA pages
  render through: `EvidenceAnswer` shows the answer, confidence, verification note, and
  limitations, then a list of `<details>`-based claim cards, each expandable (no JS beyond
  native `<details>`) to show its supporting numbers, calculations, document passages
  (with confidence, section, and page), and deduplicated sources.
- `src/pages/Home.jsx`, `CompaniesPage.jsx`, `RankingsPage.jsx` — market overview,
  sector-filterable company list, metric-ranking leaderboard.
- `src/pages/CompanyPage.jsx` + `src/pages/company/*.jsx` — a company detail shell with
  Financials / Ratios / Trends / Segments / Peer Comparison tabs and a
  Consolidated/Standalone basis toggle (`basis` state threaded into every API call the
  active tab makes).
- `src/pages/ResearchPage.jsx`, `QaPage.jsx` — the two entry points into
  `EvidenceClaims.jsx`.

The basis toggle exists specifically because insurers and some other filers only report on
one basis; rather than the dashboard guessing which basis to show, the user picks, and an
unavailable basis shows honestly as unavailable.

---

## 14. Deployment

### Full stack via Docker Compose

```bash
cd deployment/compose
docker compose up -d --build postgres minio minio-init api dashboard prometheus grafana
```

| Service | Purpose | Host port |
|---|---|---|
| `postgres` | PostgreSQL + pgvector | 55432 → 5432 |
| `minio` / `minio-init` | S3-compatible object storage for filing PDFs; `minio-init` creates the bucket and exits | 9000 (API), 9001 (console) |
| `api` | The FastAPI app, talking to `postgres` over the compose network | 8010 |
| `dashboard` | Static build served by nginx, reverse-proxying `/api/*` and `/health` to the `api` service so the browser only ever talks to one port | 5174 |
| `prometheus` | Scrapes `api:8010/metrics` every 15s | 9090 |
| `grafana` | Pre-provisioned "Fin·QA v2 — Overview" dashboard (login `admin` / `finqa12345`) | 3000 |
| `worker` (`profiles: ["tools"]`, not started by `up`) | One-shot dataset/index rebuild commands, packaged as a container instead of requiring a local Python env | — |

`api`'s `database/data/` mount is **read-only**; `worker`'s is **read-write**. Both
`data_extraction/data/` and `database/data/` are host bind mounts, not Docker volumes —
they hold the real dataset and nothing here recreates it.

One-time, once `postgres` is healthy, load your local dataset into it:

```bash
export FINQA_PG_URL=postgresql://finqa:finqa@localhost:55432/finqa
python -m finqa_v2.postgres.migrate
```

Re-run any time your local `finqa_v2.db` changes — `migrate` truncates and refills every
table (idempotent) including `document_chunks.embedding`.

Run the worker on demand:

```bash
docker compose run --rm worker python -m finqa_v2.dataset.build --skip-docs
docker compose run --rm worker python -m finqa_v2.retrieval.build_indexes
```

Sync filing PDFs to object storage (optional; ingestion itself still reads from local disk
today):

```bash
pip install -e ".[storage]"
python deployment/scripts/sync_pdfs_to_object_storage.py \
    --endpoint-url http://localhost:9000 --access-key finqa --secret-key finqa12345
```

### Images

`deployment/docker/api.Dockerfile` and `worker.Dockerfile` install the CPU-only torch
wheel explicitly, before the rest of the dependencies — the default PyPI `torch` package
pulls in the full CUDA runtime, which is several unnecessary gigabytes in a container with
no GPU. Both run as an unprivileged `finqa` user, not root.
`deployment/docker/dashboard.Dockerfile` is a multi-stage build: `node:20-slim` builds the
Vite bundle (`VITE_API_BASE_URL` baked in as a build arg), then `nginx:1.27-alpine` serves
it with an SPA-fallback config.

### Running components individually (no Docker)

You still need a local Python environment and a built `finqa_v2.db` (§4) either way.

```bash
finqa-api-v2                                   # or: uvicorn finqa_v2.api.main:app --port 8010
cd dashboard_v2 && npm install && npm run dev -- --port 5174
```

Individual (non-Compose) runs default to SQLite; set `FINQA_PG_URL` to point at Postgres
instead — no code change either way.

---

## 15. Observability

Every metric is written from a choke point the system already runs through — there is no
parallel accounting path that could drift from what actually happened.

| Metric | Written from |
|---|---|
| `finqa_http_requests_total`, `finqa_http_request_duration_seconds` | The API's request middleware, labelled by route **template** (`/api/v2/companies/{ticker}`, never the literal ticker — this bounds label cardinality regardless of how many companies exist). |
| `finqa_tool_calls_total`, `finqa_tool_call_duration_seconds` | `ToolRegistry.call()` — every deterministic answer and every LLM-planned tool call passes through here. |
| `finqa_llm_requests_total`, `finqa_llm_tokens_total`, `finqa_llm_cost_usd_total` | `RateBudget.record()` (Groq) / `CostBudget.record()` (Anthropic) — the same accounting the budget guards themselves use. |
| `finqa_verification_status_total` | `Verifier.verify()`'s own `passed`/`passed_with_warnings`/`abstained` verdict. |
| `finqa_answer_cache_events_total{cache,outcome}` | The `/qa` and `/research` LRU caches (§12). |
| `finqa_eval_baseline_accuracy`, `finqa_eval_baseline_info` | Re-read from the pinned regression-gate baseline JSON on every `/metrics` scrape — reflects the last time someone ran the eval and updated the pinned baseline, **not** a continuously running live evaluation. |

Prometheus scrapes `api:8010/metrics` every 15 seconds; Grafana's provisioned
"Fin·QA v2 — Overview" dashboard (`deployment/observability/grafana/`) plots HTTP request
rate/latency by route, HTTP 5xx rate, tool-call error rate/latency by tool, LLM requests by
provider, cumulative Anthropic cost, a verification-outcomes breakdown, the answer-cache
hit rate, and the pinned eval-baseline accuracy.

### Logging

`finqa_v2/observability/logging_config.py:configure_logging()` (called once at process
start) attaches a request id to every log line emitted during a request's lifetime, via a
`contextvars.ContextVar` set by the API middleware and echoed as the `X-Request-ID`
response header. Set `FINQA_V2_LOG_JSON=1` for one structured JSON line per event
(production); the default is plain text for a dev terminal. This is deliberately not a
distributed tracing backend (Jaeger/Tempo) — a single-service deployment this size doesn't
need one; grepping one request id across the log stream gives the same answer.

---

## 16. Security

- **API-key authentication** (`FINQA_V2_API_KEY`), when set, is enforced by middleware for
  **every** route except `/health` and `/metrics` — not per-router, so a new router can't
  accidentally ship unauthenticated. Send the key as the `X-API-Key` header.
- **Two rate limits**, both per client IP on a rolling 60-second window: a general one
  (`FINQA_V2_RATE_LIMIT`, default 120/min) on every route except `/health`/`/metrics`, and a
  stricter one (`FINQA_V2_QA_RATE_LIMIT`, default 10/min) added on top for `/qa` and
  `/research`, since an LLM call there has real cost. An unauthenticated or wrong-key
  request is rejected before it can spend a rate-limit slot.
- **Input validation**: `/qa`'s question body has both a minimum and a `max_length=2000`
  with whitespace stripped (so a whitespace-only string can't slip past the length check);
  every ticker path parameter is validated against a pattern matching real NSE tickers
  (including `M&M`, `BAJAJ-AUTO`) before it ever reaches a database lookup.
- **No path traversal surface**: document/source lookups take an integer id resolved
  server-side against the database — a user-supplied string never becomes part of a
  filesystem path.
- **No secret ever reaches a log line** — audited directly (every place an API key or
  request header could reach the logger).
- **Docker hardening**: the `api` and `worker` images run as an unprivileged `finqa` user,
  not root, since both process untrusted HTTP input or run against real data all day.

---

## 17. Evaluation framework

`evaluation/` (top-level, not inside `finqa_v2/`) is a separate, standalone scoring
framework — deterministic by default, spending zero LLM tokens unless you pass `--llm`.

### Evaluators (`evaluation/evaluators/`)

| Evaluator | Scores |
|---|---|
| `NumericalEvaluator` | Numeric answer accuracy against engine-generated gold, exact-match and tolerance-based. |
| `RetrievalEvaluator` | Recall@{1,3,5,10}, MRR, nDCG@{1,3,5,10}, p50 latency per retrieval mode. |
| `GroundednessEvaluator` | Fraction of claims whose every cited evidence/calculation id is real and not flagged unsupported by verification. |
| `CitationEvaluator` | Precision/recall/F1 of cited sources against a reference source list. |
| `CorrectnessEvaluator` | Numeric delegates to `NumericalEvaluator`; text-answer correctness via keyword coverage. |
| `AbstentionEvaluator` | Whether the system correctly refuses to answer an unanswerable/adversarial question (the safety metric) without over-abstaining on answerable ones. |
| `UnsupportedClaimEvaluator` | Rate of claims left `not_supported` or uncited. |
| `OperationsEvaluator` | Latency percentiles, tool calls per question, token usage and estimated cost. |

### The internal benchmark: FinQA-India

`evaluation/datasets/finqa_india/` generates and audits an 850-question benchmark spanning
factual, numerical, comparison, multi-step, why, how, causal, cross-document, analytical,
and adversarial categories across all 50 NIFTY 50 names. Every numeric question is
**engine-probed at generation time** — a candidate question is only kept once
`get_metric`/`get_ratio`/`get_valuation`/`get_growth` actually resolves it, so no numeric
row in the shipped dataset is unanswerable by construction; its gold value comes straight
from the `EngineResult`.

```bash
python -m evaluation.datasets.finqa_india.build --target 850 --seed 20
python -m evaluation.runners.v2_runner --dataset evaluation/datasets/finqa_india.jsonl
python -m evaluation.runners.v2_runner --dataset evaluation/datasets/finqa_india.jsonl --llm --sample 20
```

### Regression gate

`evaluation/regression/compare.py` compares any new run against a pinned baseline
(`evaluation/regression/baselines/deterministic_v2.json`) across 13 tracked metrics and
exits non-zero on a regression beyond tolerance — usable as a CI check on any change that
touches the reasoning pipeline.

### Baseline comparison (`evaluation/baselines/`)

Four pipelines, scored identically, isolate what each architectural layer contributes:

| Baseline | What it has |
|---|---|
| A — LLM only | No tools, no evidence, no citations. Whatever the model already knows. |
| B — Vector RAG | Dense retrieval only, straight to an LLM. No engine, no calculator, no verification. |
| C — Financial Engine + LLM | One direct engine call per named company, handed to the LLM to phrase. No documents, no verification. |
| D — Full Fin·QA | The real pipeline: planner + engine + hybrid retrieval + calculator + reasoning + verification. |

At n=204 real questions (Claude Sonnet, hard dollar cap): numeric accuracy is **0.0–4.2%
without the deterministic engine (A, B) and 83–92% with it (C, D)** — the categorical
finding replicates at scale and doesn't depend on which LLM answers. Groundedness (1.00)
and abstention accuracy (0.988) are only meaningful for D, since A/B/C build no claim graph
at all — there is nothing there to audit per-claim, which is itself the sharper
differentiator. Run `python -m evaluation.baselines.runner --dataset ... --sample N --llm`
to reproduce on your own key.

---

## 18. Known limitations

These are architectural facts, not bugs — the system reports them as `limitations` in its
own answers rather than working around them silently:

- **Historical depth is shallow.** Structured financials only go back to FY2025 — India's
  SEBI integrated-filing API (the only automated source of structured XBRL) doesn't serve
  anything earlier. A question about an older fiscal year gets an honest "not available,"
  never a substituted year's figure. `yoy == cagr` follows directly from this.
- **Segment margin is never shown, only segment revenue.** The XBRL segment tags carry
  revenue and a segment name but no result/profit figure; the system doesn't approximate
  one.
- **The consolidated/standalone toggle is manual, not automatic**, by design — an insurer
  that files only standalone won't have that basis silently substituted for "consolidated."
- **Reranking and hybrid-vs-lexical retrieval mode are both defaulted based on measured,
  genuinely inconclusive evidence at current corpus size** — see §6. Re-measure on a larger
  or different corpus before assuming either default is optimal for your data.
- **PostgreSQL support is tested and complete, but running components individually (not
  via Docker Compose) defaults to SQLite.** Switching is one environment variable
  (`FINQA_PG_URL`), never a code change.
- **The Postgres connection layer serializes all access behind one lock** (needed for
  correctness — see §3) which caps raw engine throughput around ~1,000 ops/second. Measured
  and left as-is: far beyond any realistic load at this scale, and a real connection pool
  would add real risk to code that took real effort to make provably thread-safe.

---

## 19. Development workflow

### Running tests

```bash
python -m unittest discover -s finqa_v2      # the core system
python -m unittest discover -s evaluation    # the evaluation framework
```

Tests gated on real infrastructure (a live database, `FINQA_LLM_TESTS=1` for real LLM
calls, `FINQA_PG_URL` for the Postgres suite) skip cleanly when that infrastructure isn't
present — a fresh clone with no dataset built yet should still show passes, not errors, on
everything that doesn't need one.

### Adding a new ratio

1. Add a `RatioSpec` to `finqa_v2/engine/ratios.py`'s registry (name, unit, required
   inputs, formula).
2. If it needs a derived quantity not already in `derive.py`, add it there.
3. Add a test in `finqa_v2/engine/tests/test_units_math.py` and, if it changes
   `compare_companies`/`decompose_metric` routing, in `test_engine.py`.
4. The tool layer, the API, and the planner all pick up a new ratio automatically through
   `engine.get_ratio()` — no changes needed there unless the ratio needs a new metric
   phrase in `planner/rules.py` for natural-language matching.

### Adding a new tool

Tools are the LLM-safety boundary — anything a reasoning LLM can trigger must be one.
Register a new function in the relevant `tools/*.py` module wrapped in `base.Tool`, add it
to `tools/registry.py:build_default_registry`, and give it a pydantic input model so
`.schema()` produces a valid function-calling schema.

### Code style in this repo

Module-level docstrings stay to one line; design rationale for a whole subsystem belongs
in this manual (or, for AI-session working notes, `docs/file-guide.md`, which is
gitignored and not meant as shipped documentation). Function and method docstrings and
inline comments explaining a non-obvious decision are normal and expected.

---

## 20. Troubleshooting

**"No module named finqa_v2" / import errors running a CLI command.** Run every
`python -m finqa_v2.*` command from the repository root, in the project's own virtual
environment (`pip install -e .` first).

**`finqa_v2.db` doesn't exist / most endpoints return 503.** Run
`python -m finqa_v2.dataset.build` first — the API refuses to serve a request that lands
before the database and engine finish initializing (`EngineNotReadyError`), and every
endpoint needs a built database regardless.

**A ratio you expect to see real data for keeps returning `None`.** Check the `limitations`
string the engine attaches to the `EngineResult` — it names the exact reason (bank/insurer
without the expected tag, no data for the requested period, missing balance-sheet
component). This is by design, not a bug to route around; see §18.

**An unqualified question returns a suspiciously small ratio (roughly a quarter of the
expected annual figure).** You're hitting the bare-`"latest"`-resolves-to-latest-quarter
pitfall described in §5 — pass an explicit `period=FY20XX` or `period=latest_annual`.

**`torch`/`sentence-transformers` errors, or embedding/reranking is extremely slow.** The
base install is CPU-only; a CUDA GPU needs a matching torch build
(`pip install torch --index-url https://download.pytorch.org/whl/cu121` or the index for
your driver) and `--device cuda` on `retrieval/build_indexes.py`. Building the dense vector
index or running the cross-encoder reranker without one still works, just slower.

**A concurrent-request 502 with a nonsensical error** (e.g. "unknown company: TCS" for a
company that obviously exists). If you're running a modified fork against SQLite or
Postgres with your own connection-handling changes, you've likely reintroduced the
same-class concurrency bug documented in §3 — Python's `sqlite3`/`psycopg` client libraries
do not guarantee true concurrent safety for one shared connection object even when the
underlying C library advertises it; route all access through a lock that also owns
row-materialization, not just the initial `execute()` call.

**Groq calls suddenly start failing with `LLMBudgetExceededError`.** You've hit the
free-tier budget guard (§11) — this is intentional, and every LLM-touching code path
degrades to a deterministic answer rather than erroring out to the user. Raise
`FINQA_LLM_TPD`/`FINQA_LLM_MAX_REQUESTS` if you have more Groq headroom, or configure
`ANTHROPIC_API_KEY` for the paid path.

---

## 21. Full environment variable reference

| Variable | Default | Used by |
|---|---|---|
| `GROQ_API_KEY` | — | `finqa_v2/llm/provider.py` |
| `ANTHROPIC_API_KEY` | — | `finqa_v2/llm/provider.py` |
| `FINQA_LLM_DISABLED` | unset | Kill switch — forces `NullProvider` regardless of keys present. |
| `FINQA_LLM_MAX_REQUESTS` | 60 | Groq `RateBudget` hard request cap per process. |
| `FINQA_LLM_RPM` | 25 | Groq `RateBudget` soft requests-per-minute throttle. |
| `FINQA_LLM_TPM` | 7000 | Groq `RateBudget` soft tokens-per-minute throttle. |
| `FINQA_LLM_TPD` | 180000 | Groq `RateBudget` hard tokens-per-day cap. |
| `FINQA_LLM_TESTS` | unset | Set to `1` to run tests that make real LLM calls (otherwise skipped). |
| `FINQA_PG_URL` / `DATABASE_URL` | unset | Selects `PgRepositories` over SQLite (`finqa_v2/db.py`). |
| `FINQA_V2_DB_PATH` | package default | Path to `finqa_v2.db`. |
| `FINQA_V2_API_HOST` | `0.0.0.0` | API bind host. |
| `FINQA_V2_API_PORT` | `8010` | API bind port. |
| `FINQA_V2_API_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins. |
| `FINQA_V2_API_KEY` | unset | If set, required as `X-API-Key` on every route except `/health`/`/metrics`. |
| `FINQA_V2_RATE_LIMIT` | 120 | General per-IP requests/min; ≤0 disables. |
| `FINQA_V2_QA_RATE_LIMIT` | 10 | Additional per-IP requests/min on `/qa` and `/research`; ≤0 disables. |
| `FINQA_V2_NO_RETRIEVER` | unset | Set to `1` to start without BM25/vector wiring (deterministic endpoints unaffected). |
| `FINQA_V2_RERANK` | `0` | Set to `1` to enable the cross-encoder reranker (see §6 for why it's off by default). |
| `FINQA_V2_BM25_PATH` | `database/data/finqa_v2_bm25.pkl` | BM25 index location. |
| `FINQA_V2_VECTOR_DIR` | `database/data/finqa_v2_vec` | Dense vector index location. |
| `FINQA_V2_LOG_JSON` | unset | Set to `1` for structured JSON logs. |
| `FINQA_V2_EVAL_BASELINE_PATH` | shipped `deterministic_v2.json` | Baseline surfaced via `/metrics`' eval gauges. |

---

## 22. Full command reference

```bash
# Dataset
python -m finqa_v2.dataset.build [--from STEP] [--skip-docs] [--no-tables] [--company TICKER]
python -m finqa_v2.dataset.audit [--json OUT] [--check]

# Search indexes
python -m finqa_v2.retrieval.build_indexes [--vector] [--device auto|cuda|cpu]
python -m finqa_v2.retrieval.evaluate [--filter-company] [--rerank]

# Raw data fetch (from data_extraction/)
python -m src.fetch.annual_reports --symbols TICKER --years N [--dry-run]
python -m src.fetch.annual_reports --all --years N --kinds transcript investor_presentation

# API
finqa-api-v2
uvicorn finqa_v2.api.main:app --port 8010

# Dashboard
npm --prefix dashboard_v2 install
npm --prefix dashboard_v2 run dev -- --port 5174
npm --prefix dashboard_v2 run build

# PostgreSQL
python -m finqa_v2.postgres.migrate

# Scale report
python -m finqa_v2.scale.report [--json OUT] [--repeats N] [--no-retriever]

# Tests
python -m unittest discover -s finqa_v2
python -m unittest discover -s evaluation

# Evaluation
python -m evaluation.datasets.finqa_india.build [--target 850] [--seed N]
python -m evaluation.runners.v2_runner --dataset PATH [--llm] [--sample N] [--sample-seed N]
python -m evaluation.regression.compare BASELINE CANDIDATE [--update]
python -m evaluation.baselines.runner --dataset PATH [--sample N] [--llm] [--provider groq|anthropic] [--total-cost-usd N]

# Docker Compose
docker compose -f deployment/compose/docker-compose.yml up -d --build postgres minio minio-init api dashboard prometheus grafana
docker compose -f deployment/compose/docker-compose.yml run --rm worker <command>
docker compose -f deployment/compose/docker-compose.yml down [-v]
```

---

Licensed under MIT — see [`LICENSE`](./LICENSE). For the quick pitch and a five-minute
setup, see [`README.md`](README.md).
