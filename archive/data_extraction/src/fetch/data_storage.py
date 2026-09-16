"""
Storage helpers. Keeps the on-disk layout consistent across sources
(NSE, BSE) and idempotent (re-running the pipeline should not
re-download files you already have).
"""
import hashlib
import json
from pathlib import Path

from src.config import RAW_DIR, META_DIR


def company_raw_dir(nse_symbol: str) -> Path:
    d = RAW_DIR / nse_symbol
    d.mkdir(parents=True, exist_ok=True)
    return d


def meta_index_path(nse_symbol: str) -> Path:
    return META_DIR / f"{nse_symbol}_filings.jsonl"


def already_downloaded(nse_symbol: str, source_url: str) -> bool:
    """Check the metadata index to avoid re-downloading the same filing."""
    path = meta_index_path(nse_symbol)
    if not path.exists():
        return False
    with open(path, "r") as f:
        for line in f:
            record = json.loads(line)
            if record.get("source_url") == source_url:
                return True
    return False

def find_existing_record_by_hash(nse_symbol: str, sha256: str) -> dict | None:
    path = meta_index_path(nse_symbol)
    if not path.exists():
        return None
    with open(path, "r") as f:
        for line in f:
            record = json.loads(line)
            if record.get("sha256") == sha256:
                return record
    return None

def append_meta_record(nse_symbol: str, record: dict):
    """Append one filing's metadata as a JSON line (append-only audit trail)."""
    path = meta_index_path(nse_symbol)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def safe_filename(text: str, max_len: int = 120) -> str:
    """Turn an arbitrary announcement subject/title into a safe filename."""
    keep = "".join(c if c.isalnum() or c in " -_." else "_" for c in text)
    keep = "_".join(keep.split())
    return keep[:max_len]


def file_hash(filepath: Path) -> str:
    """SHA256 of a downloaded file — store this in metadata so you can
    detect if a company silently re-files a 'corrected' version later."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
