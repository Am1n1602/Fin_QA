"""
api/config.py -- plain environment-variable configuration, matching the
style already used across the project (qa_router/src/config.py,
database/src/config.py): module-level constants, no config framework.

All of these can be overridden without touching code:

    FINQA_DB_PATH            -- path to financial_intelligence.db
                                 (default: database/data/financial_intelligence.db,
                                 via qa_router's own src.config.DB_PATH)
    FINQA_API_HOST            -- default 0.0.0.0
    FINQA_API_PORT            -- default 8000
    FINQA_API_CORS_ORIGINS    -- comma-separated origins, "*" for all (dev only)
    FINQA_API_KEY              -- if set, every request must send it back in
                                    the X-API-Key header. Empty/unset disables
                                    the check entirely (fine for local/dev use
                                    behind your own network boundary; set this
                                    before exposing the API beyond localhost).
    FINQA_QA_DEFAULT_K          -- default passage count for narrative/complex
                                     QA retrieval (default 5, same as qa_router's
                                     own default in src/qa.py).
    FINQA_QA_RATE_LIMIT_PER_MINUTE -- max /qa and /companies/{symbol}/qa calls
                                     allowed per client IP per rolling 60s
                                     window (default 10). This is this app's
                                     own abuse guard for a public demo --
                                     distinct from (and in front of)
                                     llm_router's GroqClient.max_calls_per_process,
                                     which protects the whole process's shared
                                     call budget once it's already been spent;
                                     this one stops a single caller from
                                     spending it for everyone else in the
                                     first place. Set to 0 (or negative) to
                                     disable. See api/deps.py's rate_limit_qa().
"""

from __future__ import annotations

import os

HOST = os.environ.get("FINQA_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("FINQA_API_PORT", "8000"))

_raw_origins = os.environ.get("FINQA_API_CORS_ORIGINS", "*")
CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

API_KEY = os.environ.get("FINQA_API_KEY", "")
API_KEY_HEADER = "X-API-Key"

DEFAULT_FILING_TYPE = "consolidated"
QA_DEFAULT_K = int(os.environ.get("FINQA_QA_DEFAULT_K", "5"))
QA_RATE_LIMIT_PER_MINUTE = int(os.environ.get("FINQA_QA_RATE_LIMIT_PER_MINUTE", "10"))