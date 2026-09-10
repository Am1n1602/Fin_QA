"""Backfill v2 companies / indices / index_memberships / one provenance source from the
v1 DB + the universe cache. No facts or documents. Idempotent. See docs/file-guide.md."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

from database.v2.models import Company, Index, IndexMembership, Source
from database.v2.sqlite import DEFAULT_V2_DB_PATH, SqliteRepositories

_REPO_ROOT = Path(__file__).resolve().parents[2]
_V1_DB = _REPO_ROOT / "database" / "data" / "financial_intelligence.db"
_UNIVERSE = _REPO_ROOT / "data_extraction" / "data" / "universe" / "nifty50_constituents.json"
_NIFTY50_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"


def _load_v1_companies(v1_db: Path) -> dict[str, dict]:
    if not v1_db.exists():
        return {}
    conn = sqlite3.connect(str(v1_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT symbol, name, bse_scrip, sector FROM companies").fetchall()
    finally:
        conn.close()
    return {r["symbol"]: dict(r) for r in rows}


def _load_universe(path: Path) -> tuple[dict[str, dict], str | None]:
    """Returns ({symbol_or_alias -> entry}, updated_at_iso)."""
    if not path.exists():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    updated_at = payload.get("updated_at")
    by_key: dict[str, dict] = {}
    for e in payload.get("companies", []):
        for key in (e.get("nse_symbol"), e.get("live_symbol")):
            if key:
                by_key.setdefault(key, e)
    return by_key, updated_at


def _updated_at_date(updated_at: str | None) -> date | None:
    if not updated_at:
        return None
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(updated_at[:10])
        except ValueError:
            return None


def build_plan(v1_db: Path, universe: Path) -> dict:
    v1 = _load_v1_companies(v1_db)
    uni_by_key, updated_at = _load_universe(universe)

    # canonical ticker set: everything with data (v1) plus everything currently in the
    # index (universe cache). Universe entries key off nse_symbol.
    uni_symbols = {e["nse_symbol"] for e in uni_by_key.values() if e.get("nse_symbol")}
    all_symbols = sorted(set(v1) | uni_symbols)

    companies: list[Company] = []
    current_members: list[str] = []
    historical_members: list[str] = []

    for sym in all_symbols:
        uni = uni_by_key.get(sym)
        v1row = v1.get(sym)

        name = (uni or {}).get("name") or (v1row or {}).get("name") or sym
        isin = (uni or {}).get("isin")
        sector = (uni or {}).get("sector") or (v1row or {}).get("sector")
        bse_scrip = (uni or {}).get("bse_scrip") or (v1row or {}).get("bse_scrip")

        in_current_index = sym in uni_symbols
        # active: trust the universe cache when present; otherwise a company that only
        # exists in v1 and is no longer in the index is inactive.
        if uni is not None:
            active = bool(uni.get("active", True))
        else:
            active = not (v1row is not None and not in_current_index)

        aliases = set()
        if uni is not None:
            for k in (uni.get("nse_symbol"), uni.get("live_symbol")):
                if k and k != sym:
                    aliases.add(k)

        companies.append(
            Company(
                name=name, ticker=sym, isin=isin, sector=sector,
                industry=None, active=active, bse_scrip=bse_scrip,
                aliases=tuple(sorted(aliases)),
            )
        )
        (current_members if in_current_index else historical_members).append(sym)

    return {
        "updated_at": updated_at,
        "companies": companies,
        "current_members": current_members,
        "historical_members": historical_members,
        "counts": {
            "companies": len(companies),
            "current_members": len(current_members),
            "historical_members": len(historical_members),
            "v1_only": sorted(set(v1) - uni_symbols),
            "index_only": sorted(uni_symbols - set(v1)),
        },
    }


def run_import(
    v1_db: Path = _V1_DB,
    universe: Path = _UNIVERSE,
    v2_db: Path = DEFAULT_V2_DB_PATH,
    index_name: str = "NIFTY 50",
    dry_run: bool = False,
) -> dict:
    plan = build_plan(v1_db, universe)
    updated = _updated_at_date(plan["updated_at"])

    if dry_run:
        c = plan["counts"]
        print(f"[dry-run] v2 db target      : {v2_db}")
        print(f"[dry-run] index             : {index_name}")
        print(f"[dry-run] universe updated  : {plan['updated_at']}")
        print(f"[dry-run] companies to upsert: {c['companies']}")
        print(f"[dry-run] current members   : {c['current_members']}")
        print(f"[dry-run] historical members: {c['historical_members']} {c['v1_only'] or ''}")
        print(f"[dry-run] in index, no data : {c['index_only'] or '(none)'}")
        return plan

    with SqliteRepositories(v2_db) as repos:
        # Deterministic hash so re-running with the same universe cache de-dups the
        # provenance row instead of appending a duplicate.
        src_hash = hashlib.sha256(
            f"index_csv|{_NIFTY50_CSV_URL}|{index_name}|{plan['updated_at']}".encode()
        ).hexdigest()
        src = repos.sources.add(
            Source(
                kind="index_csv",
                document_title=f"{index_name} constituents",
                uri=_NIFTY50_CSV_URL,
                content_hash=src_hash,
                retrieved_at=datetime.fromisoformat(plan["updated_at"].replace("Z", "+00:00"))
                if plan["updated_at"] else None,
                period_label=plan["updated_at"],
            )
        )
        index = repos.indices.upsert(Index(name=index_name, provider="NSE"))

        n_alias = 0
        current = set(plan["current_members"])
        for company in plan["companies"]:
            stored = repos.companies.upsert(company)
            n_alias += len(stored.aliases)
            is_current = company.ticker in current
            repos.indices.set_membership(
                IndexMembership(
                    index_id=index.index_id,
                    company_id=stored.company_id,
                    valid_from=None,                       # membership start unknown
                    valid_to=None if is_current else updated,  # dropped: closed at last refresh
                )
            )
        repos.commit()

        result = {
            "v2_db": str(v2_db),
            "source_id": src.source_id,
            "index_id": index.index_id,
            "companies_upserted": plan["counts"]["companies"],
            "aliases": n_alias,
            "current_members": plan["counts"]["current_members"],
            "historical_members": plan["counts"]["historical_members"],
        }

    print(
        f"[import] {result['companies_upserted']} companies, {result['aliases']} aliases, "
        f"index '{index_name}' (id={result['index_id']}), "
        f"{result['current_members']} current + {result['historical_members']} historical members "
        f"-> {result['v2_db']}"
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--v1-db", type=Path, default=_V1_DB)
    ap.add_argument("--universe", type=Path, default=_UNIVERSE)
    ap.add_argument("--v2-db", type=Path, default=DEFAULT_V2_DB_PATH)
    ap.add_argument("--index-name", default="NIFTY 50")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run_import(args.v1_db, args.universe, args.v2_db, args.index_name, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
