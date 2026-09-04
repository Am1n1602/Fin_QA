"""
data_extraction/src/universe.py

Resolves the NIFTY 50 constituent list at run time instead of treating
`config.COMPANIES` as a fixed, hand-maintained set 

"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

import requests

from src.config import BASE_DIR, USER_AGENT, REQUEST_DELAY_SECONDS
from src.fetch import bse_source

UNIVERSE_DIR = BASE_DIR / "data" / "universe"
UNIVERSE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_PATH = UNIVERSE_DIR / "nifty50_constituents.json"


NIFTY50_CSV_URL = "https://archives.nseindia.com/content/indices/ind_nifty50list.csv"

NSE_HOME_URL = "https://www.nseindia.com"

_NAME_COLS = ("company name", "companyname")
_SYMBOL_COLS = ("symbol",)
_ISIN_COLS = ("isin code", "isin")


def _normalize_header(h: str) -> str:
    return h.strip().lower()


def _pick(row: dict, candidates: tuple[str, ...]) -> str | None:
    for key, value in row.items():
        if _normalize_header(key) in candidates:
            return (value or "").strip()
    return None


def _scrip_lookup_variants(entry: dict) -> list[str]:
    """Ordered list of query strings to try against BSE's lookup, most
    likely to work first (symbol, per the library's own documented
    usage) to least (raw company name). Deduplicated, order-preserving."""
    candidates = [entry["nse_symbol"], entry["name"]]
    seen = set()
    out = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def fetch_nifty50_index_csv(timeout: int = 20) -> list[dict] | None:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    try:

        session.get(NSE_HOME_URL, timeout=timeout)
    except requests.RequestException as e:
        print(f"[universe] NSE homepage warm-up request failed (continuing anyway): {e}")

    try:
        resp = session.get(NIFTY50_CSV_URL, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[universe] Failed to fetch live NIFTY 50 list from {NIFTY50_CSV_URL}: {e}")
        return None

    try:
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as e:
        print(f"[universe] Downloaded NIFTY 50 CSV but couldn't parse it as CSV: {e}\n"
              f"  First 200 bytes: {resp.content[:200]!r}")
        return None

    if not rows:
        print(f"[universe] Downloaded NIFTY 50 CSV but it had zero data rows -- treating as a failure.")
        return None

    # First live run: print the raw header so a schema drift is visible
    # immediately, the same discipline nse_source.py already documents.
    print(f"[universe] Live NIFTY 50 CSV columns: {list(rows[0].keys())}")

    companies = []
    skipped = 0
    for row in rows:
        name = _pick(row, _NAME_COLS)
        symbol = _pick(row, _SYMBOL_COLS)
        isin = _pick(row, _ISIN_COLS)
        if not name or not symbol:
            skipped += 1
            continue
        companies.append({"name": name, "nse_symbol": symbol, "isin": isin})

    if skipped:
        print(f"[universe] {skipped} row(s) skipped -- missing a name or symbol "
              f"(check the column-name mapping above if this is more than a handful).")

    if not companies:
        print("[universe] Parsed the CSV but extracted zero usable rows -- "
              "the column names above don't match what this parser expects. "
              "Treating as a failure rather than caching an empty universe.")
        return None

    if len(companies) != 50:
        print(f"[universe] NOTE: parsed {len(companies)} constituents, not exactly 50. "
              f"NIFTY 50 can briefly hold a different count around a reconstitution "
              f"effective date -- not necessarily a bug, but worth a glance.")

    return companies


def _load_cache() -> dict[str, dict]:
    if not CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        print(f"[universe] Couldn't read existing cache at {CACHE_PATH} ({e}) -- starting fresh.")
        return {}
    return {entry["nse_symbol"]: entry for entry in raw.get("companies", [])}


def _save_cache(by_symbol: dict[str, dict]) -> None:
    payload = {
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "companies": sorted(by_symbol.values(), key=lambda c: c["nse_symbol"]),
    }
    CACHE_PATH.write_text(json.dumps(payload, indent=2))


def refresh(resolve_scrip_codes: bool = True) -> dict[str, dict]:

    cache = _load_cache()
    live = fetch_nifty50_index_csv()

    if live is None:
        if not cache:
            raise RuntimeError(
                "Live NIFTY 50 fetch failed AND no cache exists yet at "
                f"{CACHE_PATH} -- can't proceed with zero companies. Check "
                "network access and NIFTY50_CSV_URL, or seed the cache "
                "manually for a first run."
            )
        print(f"[universe] Live fetch failed -- keeping the existing cache "
              f"({len(cache)} companies, last updated per {CACHE_PATH}).")
        return cache

    live_symbols = {c["nse_symbol"] for c in live}

    for c in live:
        symbol = c["nse_symbol"]
        existing = cache.get(symbol)
        if existing:
            existing.update(name=c["name"], isin=c["isin"], active=True)
        else:
            cache[symbol] = {
                "name": c["name"],
                "nse_symbol": symbol,
                "isin": c["isin"],
                "bse_scrip": None,
                "active": True,
            }

    for symbol, entry in cache.items():
        if symbol not in live_symbols and entry.get("active", True):
            entry["active"] = False
            print(f"[universe] {symbol} ({entry.get('name')}) is no longer in the live "
                  f"NIFTY 50 list -- marked inactive. Its already-ingested data is left "
                  f"in place; it will simply stop being fetched/extracted/re-ingested "
                  f"going forward. Delete it from {CACHE_PATH} manually if you want it "
                  f"purged instead.")

    _save_cache(cache)

    if resolve_scrip_codes:
        missing = [e for e in cache.values() if e.get("active", True) and not e.get("bse_scrip")]
        if missing:
            print(f"[universe] Resolving BSE scrip codes for {len(missing)} new/unresolved "
                  f"compan{'y' if len(missing) == 1 else 'ies'}...")
        for entry in missing:
            scrip = None
            last_error = None
            variants = _scrip_lookup_variants(entry)
            for variant in variants:
                try:
                    scrip = bse_source.get_scrip_code(variant)
                except Exception as e:
                    last_error = e
                    scrip = None
                if scrip:
                    if variant != entry["nse_symbol"]:
                        print(f"  {entry['nse_symbol']}: matched on fallback variant '{variant}' "
                              f"(symbol '{entry['nse_symbol']}' itself didn't match)")
                    break
            if scrip:
                entry["bse_scrip"] = scrip
                print(f"  {entry['nse_symbol']}: resolved bse_scrip={scrip}")
            else:
                print(f"  {entry['nse_symbol']}: no BSE scrip code found "
                      f"(tried {variants}"
                      + (f", last error: {last_error}" if last_error else "") + ") -- "
                      f"this company will be EXCLUDED from get_companies() until it's resolved "
                      f"(re-run --refresh, or set it by hand in {CACHE_PATH}).")
            _save_cache(cache)
    else:
        _save_cache(cache)

    return cache


def get_companies() -> list[dict]:
    cache = _load_cache()
    result = []
    excluded = 0
    for entry in cache.values():
        if not entry.get("active", True):
            continue
        if not entry.get("bse_scrip"):
            excluded += 1
            continue
        result.append({
            "name": entry["name"],
            "nse_symbol": entry["nse_symbol"],
            "bse_scrip": entry["bse_scrip"],
        })
    if excluded:
        print(f"[universe] {excluded} active compan{'y is' if excluded == 1 else 'ies are'} "
              f"missing a resolved BSE scrip code and excluded from this run -- "
              f"run `python -m src.universe --refresh` to resolve them.")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true",
                     help="Fetch the live NIFTY 50 list, resolve any missing BSE scrip "
                          "codes, and update the local cache.")
    ap.add_argument("--no-resolve-scrip", action="store_true",
                     help="With --refresh, skip BSE scrip-code resolution (faster, "
                          "useful for just checking what the live list currently contains).")
    ap.add_argument("--show", action="store_true",
                     help="Print the current cached, active, fully-resolved company list.")
    args = ap.parse_args()

    if args.refresh:
        cache = refresh(resolve_scrip_codes=not args.no_resolve_scrip)
        active = sum(1 for e in cache.values() if e.get("active", True))
        resolved = sum(1 for e in cache.values() if e.get("active", True) and e.get("bse_scrip"))
        print(f"\n[universe] Cache updated: {len(cache)} total ({active} active, "
              f"{resolved} with a resolved BSE scrip code). Saved to {CACHE_PATH}")

    if args.show or not args.refresh:
        companies = get_companies()
        print(f"\n[universe] {len(companies)} companies ready for use:")
        for c in companies:
            print(f"  {c['nse_symbol']:12s} bse_scrip={c['bse_scrip']:8s} {c['name']}")


if __name__ == "__main__":
    main()