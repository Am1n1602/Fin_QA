-- Fin_QA v2 Data Foundation schema -- applied to database/data/finqa_v2.db.
-- Idempotent (CREATE ... IF NOT EXISTS). See docs/file-guide.md.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Companies & indices  (section 8 -- no NIFTY 50 hard-coding)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    company_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    ticker       TEXT    NOT NULL,
    exchange     TEXT    NOT NULL DEFAULT 'NSE',
    isin         TEXT,
    sector       TEXT,
    industry     TEXT,
    active       INTEGER NOT NULL DEFAULT 1,      -- 0/1; historical members set 0, never deleted
    bse_scrip    TEXT,
    UNIQUE (ticker, exchange)
);

CREATE TABLE IF NOT EXISTS company_aliases (
    company_id   INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    alias        TEXT    NOT NULL,
    PRIMARY KEY (company_id, alias)
);

CREATE TABLE IF NOT EXISTS indices (
    index_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,          -- 'NIFTY 50', 'NIFTY 100', 'SENSEX', 'custom:my-peers'
    provider     TEXT                              -- 'NSE' | 'BSE' | 'custom'
);

CREATE TABLE IF NOT EXISTS index_memberships (
    index_id     INTEGER NOT NULL REFERENCES indices(index_id)   ON DELETE CASCADE,
    company_id   INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    valid_from   TEXT,                              -- ISO date, inclusive; NULL = since inception / unknown
    valid_to     TEXT                               -- ISO date, exclusive; NULL = still a member
);

-- One membership window per (index, company, start). Expression index so a NULL
-- valid_from still de-dups (SQLite treats NULLs in a plain UNIQUE as distinct).
CREATE UNIQUE INDEX IF NOT EXISTS ux_membership_window
    ON index_memberships (index_id, company_id, COALESCE(valid_from, ''));

-- ---------------------------------------------------------------------------
-- Provenance  (section 9 -- every fact/document can cite a source)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sources (
    source_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,                   -- 'xbrl' | 'results_pdf' | 'annual_report' | 'price_feed' | 'index_csv'
    company_id     INTEGER REFERENCES companies(company_id) ON DELETE SET NULL,
    document_title TEXT,
    uri            TEXT,                            -- URL or local path
    content_hash   TEXT UNIQUE,                     -- sha256 of raw bytes; de-dup key
    exchange       TEXT,
    retrieved_at   TEXT,                            -- ISO datetime
    period_label   TEXT                             -- raw period string as-filed
);

-- ---------------------------------------------------------------------------
-- Canonical financial facts  (section 9)
--   value NULL  == not reported / not cleanly mappable. NEVER 0-filled.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS financial_facts (
    fact_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id         INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    metric             TEXT    NOT NULL,            -- canonical name: 'revenue', 'ebitda', 'roe', ...
    value              REAL,                        -- NULL preserved as NULL
    unit               TEXT,                        -- 'INR' | 'pct' | 'x' | 'ratio' | 'per_share' | 'shares' | 'pp'
    currency           TEXT DEFAULT 'INR',
    period_start       TEXT,                        -- ISO date; NULL for point-in-time
    period_end         TEXT,                        -- ISO date (duration end or instant)
    financial_year     INTEGER,                     -- 2026 for FY2026
    quarter            INTEGER,                     -- 1..4, or NULL for annual / point-in-time
    statement_type     TEXT    NOT NULL,            -- 'profit_and_loss' | 'balance_sheet' | 'cash_flow' | 'segment' | 'other'
    basis              TEXT    NOT NULL,            -- 'consolidated' | 'standalone'
    is_annual          INTEGER NOT NULL DEFAULT 0,
    is_point_in_time   INTEGER NOT NULL DEFAULT 0,
    source_id          INTEGER REFERENCES sources(source_id) ON DELETE SET NULL,
    mapping_confidence TEXT    NOT NULL DEFAULT 'exact',
    mapping_reason     TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_facts_grain
    ON financial_facts (
        company_id, metric, basis, statement_type,
        COALESCE(period_end, ''), COALESCE(period_start, '')
    );

-- ---------------------------------------------------------------------------
-- Documents  (parent records only; chunk storage is Phase 5)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    document_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id     INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    document_type  TEXT    NOT NULL,                -- 'results_pdf' | 'annual_report' | 'transcript' | ...
    title          TEXT    NOT NULL,
    financial_year INTEGER,
    period_label   TEXT,
    page_count     INTEGER,
    source_id      INTEGER REFERENCES sources(source_id) ON DELETE SET NULL,
    is_superseded  INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- Indexes for the common access paths
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS ix_facts_lookup        ON financial_facts (company_id, metric, basis);
CREATE INDEX IF NOT EXISTS ix_facts_fy            ON financial_facts (company_id, financial_year);
CREATE INDEX IF NOT EXISTS ix_membership_company  ON index_memberships (company_id);
CREATE INDEX IF NOT EXISTS ix_membership_current  ON index_memberships (index_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_documents_company   ON documents (company_id);
CREATE INDEX IF NOT EXISTS ix_sources_company     ON sources (company_id);
