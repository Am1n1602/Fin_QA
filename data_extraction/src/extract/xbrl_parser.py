# this can work as a fallback if we need to directly fetch it from nse/bse website

"""
Parses one XBRL instance document into the normalized schema:
company, period_start, period_end, line_item (raw XBRL tag), value, unit,
context_id, source_doc.

"""
import json
import sys
from pathlib import Path

from arelle import Cntlr

from src.config import META_DIR, USER_AGENT


def find_source_url(local_path: str, symbol: str) -> str | None:
    """Look up the original NSE/BSE URL for a locally downloaded file,
    from this company's metadata index (data/meta/{symbol}_filings.jsonl).
    Needed because parsing must happen against the original URL, not the
    local copy"""
    meta_path = META_DIR / f"{symbol}_filings.jsonl"
    if not meta_path.exists():
        return None
    local_path_resolved = str(Path(local_path).resolve())
    with open(meta_path, "r") as f:
        for line in f:
            record = json.loads(line)
            if str(Path(record.get("local_path", "")).resolve()) == local_path_resolved:
                return record.get("source_url")
    return None


def parse_xbrl_file(filepath: str, company: str = "", skip_dts: bool = True) -> list[dict]:
    """Load one XBRL instance and return a list of normalized fact records."""
    ctrl = Cntlr.Cntlr(logFileName="logToPrint")  # change to None to remove diagnostis
    ctrl.modelManager.skipDTS = skip_dts
    ctrl.webCache.httpUserAgent = USER_AGENT
    model = ctrl.modelManager.load(filepath)

    if model is None or not model.facts:
        print(f"[xbrl_parser] WARNING: no facts loaded from {filepath}. "
              f"Likely a taxonomy/schema resolution issue (network access, "
              f"or the schemaRef URL has changed) — inspect ctrl.modelManager "
              f"errors, or open the file and check the <link:schemaRef> URL.")
        ctrl.close()
        return []

    records = []
    for fact in model.facts:
        if fact.isNil:
            continue
        ctx = fact.context
        unit = fact.unit

        period_start = getattr(ctx, "startDatetime", None) if ctx is not None else None
        period_end = getattr(ctx, "endDatetime", None) if ctx is not None else None
        instant = getattr(ctx, "instantDatetime", None) if ctx is not None else None

        records.append({
            "company": company,
            "line_item_tag": str(fact.qname) if fact.qname else fact.concept.name if fact.concept else None,
            "value": fact.value,
            "unit": str(unit.measures) if unit is not None else None,
            "context_id": fact.contextID,
            "period_start": str(period_start) if period_start else None,
            "period_end": str(period_end) if period_end else None,
            "instant": str(instant) if instant else None,
            "decimals": fact.decimals,
            "source_doc": filepath,
        })

    ctrl.close()
    return records


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m src.extract.xbrl_parser <local-path-or-URL> [company_symbol]")
        print("  If a local path is given, its original URL is looked up")
        print("  automatically from data/meta/{symbol}_filings.jsonl and used")
        print("  instead — required for NSE's relative schemaRef to resolve.")
        sys.exit(1)
    arg = sys.argv[1]
    company = sys.argv[2] if len(sys.argv) > 2 else ""

    if arg.startswith("http"):
        target = arg
    else:
        resolved = find_source_url(arg, company) if company else None
        if resolved:
            print(f"[xbrl_parser] Resolved local path to original URL: {resolved}")
            target = resolved
        else:
            print(f"[xbrl_parser] WARNING: could not find a metadata record for "
                  f"'{arg}' under company '{company}' — falling back to the local "
                  f"path as-is. This will likely fail to resolve the schemaRef "
                  f"(see module docstring). Pass the symbol as the 2nd argument, "
                  f"or pass the https:// URL directly.")
            target = arg

    recs = parse_xbrl_file(target, company)
    print(f"Extracted {len(recs)} facts.")

    out_path = Path("data/extracted") / f"{company}_facts_raw.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(recs, indent=2, default=str))
    print(f"Full fact list saved to {out_path}")

    # Print only the facts whose tag name suggests it's a P&L/balance-sheet
    KEYWORDS = [
        "revenue", "income", "expense", "profit", "tax", "eps",
        "asset", "liabilit", "equity", "reserve", "borrowing",
        "depreciation", "cash", "dividend",
    ]
    print(f"\n--- Facts matching financial-statement keywords ({', '.join(KEYWORDS)}) ---")
    for r in recs:
        tag = (r["line_item_tag"] or "").lower()
        if any(kw in tag for kw in KEYWORDS):
            print(f"{r['line_item_tag']:70s} = {r['value']!s:20s} "
                  f"[ctx={r['context_id']}, period_end={r['period_end']}]")