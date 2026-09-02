CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_symbol  TEXT NOT NULL,
    source          TEXT,              -- 'NSE' or 'BSE'
    title           TEXT NOT NULL,
    also_known_as   TEXT,              -- JSON list of alternate titles (see
                                        -- clean_duplicate_downloads.py) -- same
                                        -- content filed under >1 announcement.
    period          TEXT,              -- raw period string from the inventory
                                        -- (format varies -- not normalized here)
    sha256_hash     TEXT NOT NULL UNIQUE,
    local_path      TEXT,
    page_count      INTEGER,
    is_superseded   INTEGER NOT NULL DEFAULT 0,
    ingested_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES documents(id),
    chunk_index     INTEGER NOT NULL,
    page_start      INTEGER,
    page_end        INTEGER,
    section         TEXT,              -- heuristic label from chunker.py, may be NULL
    text            TEXT NOT NULL,
    char_count      INTEGER,
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_company_symbol ON documents(company_symbol);
CREATE INDEX IF NOT EXISTS idx_documents_sha256 ON documents(sha256_hash);