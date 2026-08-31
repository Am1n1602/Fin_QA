CREATE TABLE IF NOT EXISTS companies (
    symbol TEXT PRIMARY KEY,          -- NSE symbol, e.g. "TCS"
    name TEXT,
    bse_scrip TEXT
);

CREATE TABLE IF NOT EXISTS filings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_symbol TEXT NOT NULL REFERENCES companies(symbol),
    filing_type TEXT NOT NULL,         -- 'consolidated' | 'standalone'
    context_id TEXT NOT NULL,          -- e.g. "OneD", "FourD+OneI"
    period_start TEXT,
    period_end TEXT,
    instant TEXT,
    is_single_quarter INTEGER,         -- 0/1
    is_annual INTEGER,                 -- 0/1
    has_balance_sheet INTEGER,         -- 0/1 — whether this filing includes total_assets etc.
    source_file TEXT,
    loaded_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_filings_unique
    ON filings (company_symbol, filing_type, context_id, COALESCE(period_end, ''), COALESCE(instant, ''));

-- Raw normalized facts from data_extraction's canonical schema (revenue,
-- net_profit, total_assets, ...) — the single source of truth for inputs.
CREATE TABLE IF NOT EXISTS financial_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    field_name TEXT NOT NULL,
    value REAL,
    UNIQUE (filing_id, field_name)
);
-- pe_ratio, ...) — loaded as-is from data_analysis's output, NEVER
-- recomputed here. Per roadmap Section 6: "Financial Engine is the
-- single source of truth" — this table is a read-through cache of that
-- engine's output, not an independent calculation.
CREATE TABLE IF NOT EXISTS financial_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_id INTEGER NOT NULL REFERENCES filings(id),
    metric_name TEXT NOT NULL,
    value REAL,          -- NULL preserved as NULL, never coerced to 0
    unit TEXT,            -- 'pct' | 'x' | 'count' | 'currency' | 'pp'
    UNIQUE (filing_id, metric_name)
);

CREATE TABLE IF NOT EXISTS share_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_symbol TEXT NOT NULL REFERENCES companies(symbol),
    date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL, volume REAL,
    UNIQUE (company_symbol, date)
);

CREATE INDEX IF NOT EXISTS idx_filings_company ON filings(company_symbol);
CREATE INDEX IF NOT EXISTS idx_facts_filing ON financial_facts(filing_id);
CREATE INDEX IF NOT EXISTS idx_metrics_filing ON financial_metrics(filing_id);
CREATE INDEX IF NOT EXISTS idx_prices_company_date ON share_prices(company_symbol, date);
