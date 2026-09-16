-- Fin_QA v2 schema for PostgreSQL + pgvector (§7 / §17 / §48 Phase 17).
-- Mirrors finqa_v2/sqlite/schema_v2.sql one-to-one so the repository logic is
-- unchanged: date/datetime columns stay TEXT (ISO strings), booleans stay INTEGER
-- (0/1) -- the row->model mappers and _ds/_d/_b helpers are shared with the SQLite
-- backend. The only additions are BIGINT identity keys and the pgvector column.
-- Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS companies (
    company_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         TEXT    NOT NULL,
    ticker       TEXT    NOT NULL,
    exchange     TEXT    NOT NULL DEFAULT 'NSE',
    isin         TEXT,
    sector       TEXT,
    industry     TEXT,
    active       INTEGER NOT NULL DEFAULT 1,
    bse_scrip    TEXT,
    UNIQUE (ticker, exchange)
);

CREATE TABLE IF NOT EXISTS company_aliases (
    company_id   BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    alias        TEXT   NOT NULL,
    PRIMARY KEY (company_id, alias)
);

CREATE TABLE IF NOT EXISTS indices (
    index_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         TEXT   NOT NULL UNIQUE,
    provider     TEXT
);

CREATE TABLE IF NOT EXISTS index_memberships (
    index_id     BIGINT NOT NULL REFERENCES indices(index_id)     ON DELETE CASCADE,
    company_id   BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    valid_from   TEXT,
    valid_to     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_membership_window
    ON index_memberships (index_id, company_id, COALESCE(valid_from, ''));

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sources (
    source_id      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind           TEXT NOT NULL,
    company_id     BIGINT REFERENCES companies(company_id) ON DELETE SET NULL,
    document_title TEXT,
    uri            TEXT,
    content_hash   TEXT UNIQUE,
    exchange       TEXT,
    retrieved_at   TEXT,
    period_label   TEXT
);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS financial_facts (
    fact_id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id         BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    metric             TEXT   NOT NULL,
    value              DOUBLE PRECISION,
    unit               TEXT,
    currency           TEXT DEFAULT 'INR',
    period_start       TEXT,
    period_end         TEXT,
    financial_year     INTEGER,
    quarter            INTEGER,
    statement_type     TEXT   NOT NULL,
    basis              TEXT   NOT NULL,
    is_annual          INTEGER NOT NULL DEFAULT 0,
    is_point_in_time   INTEGER NOT NULL DEFAULT 0,
    source_id          BIGINT REFERENCES sources(source_id) ON DELETE SET NULL,
    mapping_confidence TEXT   NOT NULL DEFAULT 'exact',
    mapping_reason     TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_facts_grain
    ON financial_facts (
        company_id, metric, basis, statement_type,
        COALESCE(period_end, ''), COALESCE(period_start, '')
    );

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segments (
    segment_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    slug         TEXT NOT NULL,
    UNIQUE (company_id, slug)
);

CREATE TABLE IF NOT EXISTS segment_facts (
    segment_fact_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    segment_id       BIGINT NOT NULL REFERENCES segments(segment_id) ON DELETE CASCADE,
    company_id       BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    metric           TEXT   NOT NULL,
    value            DOUBLE PRECISION,
    unit             TEXT DEFAULT 'INR',
    period_start     TEXT,
    period_end       TEXT,
    financial_year   INTEGER,
    quarter          INTEGER,
    is_annual        INTEGER NOT NULL DEFAULT 0,
    basis            TEXT   NOT NULL,
    source_id        BIGINT REFERENCES sources(source_id) ON DELETE SET NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_segment_facts_grain
    ON segment_facts (
        segment_id, metric, basis,
        COALESCE(period_end, ''), COALESCE(period_start, '')
    );
CREATE INDEX IF NOT EXISTS ix_segment_facts_company ON segment_facts (company_id, metric);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS share_prices (
    price_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id   BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    price_date   TEXT   NOT NULL,
    close        DOUBLE PRECISION,
    vwap         DOUBLE PRECISION,
    volume       DOUBLE PRECISION,
    currency     TEXT   NOT NULL DEFAULT 'INR',
    source_id    BIGINT REFERENCES sources(source_id) ON DELETE SET NULL,
    UNIQUE (company_id, price_date)
);
CREATE INDEX IF NOT EXISTS ix_prices_company ON share_prices (company_id, price_date);

-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    document_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id     BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    document_type  TEXT   NOT NULL,
    title          TEXT   NOT NULL,
    financial_year INTEGER,
    period_label   TEXT,
    page_count     INTEGER,
    source_id      BIGINT REFERENCES sources(source_id) ON DELETE SET NULL,
    is_superseded  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    BIGINT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    company_id     BIGINT NOT NULL REFERENCES companies(company_id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,
    text           TEXT   NOT NULL,
    page_start     INTEGER,
    page_end       INTEGER,
    section        TEXT,
    subsection     TEXT,
    financial_year INTEGER,
    document_type  TEXT,
    topic          TEXT,
    segment        TEXT,
    char_count     INTEGER,
    embedding      vector(384),                    -- §17 pgvector; NULL until embedded
    UNIQUE (document_id, chunk_index)
);
CREATE INDEX IF NOT EXISTS ix_chunks_document        ON document_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_chunks_company_section ON document_chunks (company_id, section);
CREATE INDEX IF NOT EXISTS ix_chunks_company_fy      ON document_chunks (company_id, financial_year);

-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_facts_lookup        ON financial_facts (company_id, metric, basis);
CREATE INDEX IF NOT EXISTS ix_facts_fy            ON financial_facts (company_id, financial_year);
CREATE INDEX IF NOT EXISTS ix_membership_company  ON index_memberships (company_id);
CREATE INDEX IF NOT EXISTS ix_membership_current  ON index_memberships (index_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS ix_documents_company   ON documents (company_id);
CREATE INDEX IF NOT EXISTS ix_sources_company     ON sources (company_id);

-- pgvector ANN index -- cosine on normalised embeddings. `lists` ~ sqrt(rows);
-- fine to create empty, rebuilt cheaply. Only used once embeddings are populated.
CREATE INDEX IF NOT EXISTS ix_chunks_embedding
    ON document_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200);
